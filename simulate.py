"""
simulate.py — Headless benchmarking harness for the Adaptive Poker Bot.

Runs N hands silently (no prints), logs every hand to CSV, then produces:
  - BB/100 win rate
  - Bluff success rate
  - Showdown win %
  - Component stats (VPIP, PFR, fold-to-3bet, etc.)
  - Win rate chart over time
"""

import random
import csv
import io
import sys
import os
import math
from dataclasses import dataclass, field, asdict
from typing import List, Optional
from contextlib import contextmanager

from treys import Card, Deck, Evaluator

from players import Player, AIOpponent
from strategy import AdaptiveStrategy
from hand_evaluator import evaluate_hand, hand_strength_percentile, rank_description

evaluator_obj = Evaluator()
RANK_CLASS_NAMES = {
    1:"Royal Flush",2:"Straight Flush",3:"Four of a Kind",
    4:"Full House",5:"Flush",6:"Straight",7:"Three of a Kind",
    8:"Two Pair",9:"Pair",10:"High Card"
}

# ─────────────────────────────────────────────────────────────
# Silence stdout during simulation
# ─────────────────────────────────────────────────────────────
@contextmanager
def silent():
    old = sys.stdout
    sys.stdout = io.StringIO()
    try:
        yield
    finally:
        sys.stdout = old


# ─────────────────────────────────────────────────────────────
# Hand log record
# ─────────────────────────────────────────────────────────────
@dataclass
class HandRecord:
    hand_num: int
    num_players: int
    bot_chips_start: int
    bot_chips_end: int
    bb: int
    bot_hole_cards: str
    preflop_action: str          # fold/call/raise
    preflop_amount: int
    reached_showdown: bool
    won_at_showdown: bool
    final_hand_name: str
    final_hand_strength: float
    bluff_attempted: bool
    bluff_succeeded: bool        # True if bluff raised and opponents folded
    pot_won: int
    community_cards: str

    @property
    def chip_delta(self):
        return self.bot_chips_end - self.bot_chips_start

    @property
    def bb_delta(self):
        return self.chip_delta / self.bb


# ─────────────────────────────────────────────────────────────
# Headless Game Engine
# ─────────────────────────────────────────────────────────────
def cards_str_short(cards):
    ranks = "23456789TJQKA"
    suits = {1:"s",2:"h",4:"d",8:"c"}
    return " ".join(ranks[Card.get_rank_int(c)] + suits.get(Card.get_suit_int(c),"?") for c in cards)


class HeadlessEngine:
    def __init__(self, players, small_blind, big_blind, strategy, bot_player):
        self.players = players
        self.sb = small_blind
        self.bb = big_blind
        self.strategy = strategy
        self.bot = bot_player
        self.dealer_idx = 0
        self.hand_num = 0

    def play_hand(self) -> HandRecord:
        self.hand_num += 1

        # Reset everyone to 100BB each hand — this bounds pot sizes realistically
        # and makes each hand independent (standard cash game benchmarking approach)
        for p in self.players:
            p.chips = 100 * self.bb
            p.reset_for_hand()

        active = [p for p in self.players if p.chips > 0]
        if len(active) < 2:
            return None

        self.dealer_idx = self.dealer_idx % len(active)

        deck = Deck()
        deck.shuffle()
        for p in active:
            p.hole_cards = deck.draw(2)

        community = []
        pot = 0

        # Blinds — post BEFORE capturing bot_chips_start so delta = net profit only
        sb_idx = (self.dealer_idx + 1) % len(active)
        bb_idx = (self.dealer_idx + 2) % len(active)
        sb_p = active[sb_idx]
        bb_p = active[bb_idx]
        pot += sb_p.place_bet(self.sb) + bb_p.place_bet(self.bb)

        # Capture start AFTER blinds so chip_delta = money won/lost beyond blind cost
        bot_chips_start = self.bot.chips

        # Track hand record fields
        record = HandRecord(
            hand_num=self.hand_num,
            num_players=len(active),
            bot_chips_start=bot_chips_start,
            bot_chips_end=bot_chips_start,
            bb=self.bb,
            bot_hole_cards=rank_description(self.bot.hole_cards) if self.bot in active else "—",
            preflop_action="fold",
            preflop_amount=0,
            reached_showdown=False,
            won_at_showdown=False,
            final_hand_name="—",
            final_hand_strength=0.0,
            bluff_attempted=False,
            bluff_succeeded=False,
            pot_won=0,
            community_cards="—"
        )

        if self.bot not in active:
            record.bot_chips_end = self.bot.chips
            return record

        # ── PRE-FLOP ──
        limpers = 0
        raises = 0
        position = self._get_position(active, self.bot, bb_idx)
        current_bet = self.bb
        to_call = current_bet - self.bot.current_bet

        # Simulate opponents acting before bot
        bot_seat = active.index(self.bot)
        start_idx = (bb_idx + 1) % len(active)

        for i in range(len(active)):
            idx = (start_idx + i) % len(active)
            p = active[idx]
            if p is self.bot:
                break
            tc = max(current_bet - p.current_bet, 0)
            tc = min(tc, p.chips)
            if hasattr(p, 'decide') and p.is_bot:
                action, amt = p.decide(tc, pot, self.bb, "preflop", [], None)
            else:
                action, amt = "fold", 0
            if action == "fold":
                p.folded = True
            elif action == "call":
                bet = p.place_bet(tc)
                pot += bet
                limpers += 1
                self.strategy.record_preflop_action(p.name, action, tc, self.bb, raises > 0)
            elif action in ("bet", "raise"):
                # amt is total raise size (not increment) — cap at chips and pot
                total = min(max(amt, tc + self.bb), p.chips)
                bet = p.place_bet(total)
                pot += bet
                current_bet = p.current_bet
                raises += 1
                self.strategy.record_preflop_action(p.name, action, total, self.bb, raises > 1)

        # Bot acts pre-flop
        to_call = max(current_bet - self.bot.current_bet, 0)
        to_call = min(to_call, self.bot.chips)
        num_active = len([p for p in active if not p.folded])

        bot_action, bot_amount = self.strategy.preflop_decision(
            self.bot.hole_cards, pot, to_call, self.bb,
            position, num_active, raises, limpers
        )
        self.strategy.flush_log()  # discard logs

        record.preflop_action = bot_action
        record.preflop_amount = bot_amount

        # Detect bluff attempt: bot raises with < 45% equity
        from hand_evaluator import estimate_preflop_strength
        eq = estimate_preflop_strength(self.bot.hole_cards)

        if bot_action == "fold":
            self.bot.folded = True
        elif bot_action == "call":
            bet = self.bot.place_bet(to_call)
            pot += bet
        elif bot_action in ("raise", "bet"):
            if eq < 0.50:
                record.bluff_attempted = True
            # bot_amount is already the total chips to put in (raise size, not increment)
            total = min(bot_amount, self.bot.chips)
            total = max(total, to_call)  # must at least call
            bet = self.bot.place_bet(total)
            pot += bet
            current_bet = self.bot.current_bet
            raises += 1

        # Remaining opponents respond to bot raise
        # Use the AI opponent's own decide() so archetype matters
        if bot_action in ("raise", "bet") and raises >= 1:
            all_folded = True
            for p in active:
                if p is self.bot or p.folded or p.all_in or p.chips == 0:
                    continue
                tc = max(current_bet - p.current_bet, 0)
                tc = min(tc, p.chips)
                if tc <= 0:
                    all_folded = False
                    continue
                if hasattr(p, 'decide') and p.is_bot:
                    from hand_evaluator import estimate_preflop_strength
                    opp_eq = estimate_preflop_strength(p.hole_cards)
                    action, amt = p.decide(tc, pot, self.bb, "preflop", [], opp_eq)
                else:
                    action = "fold"
                if action == "fold":
                    p.folded = True
                elif action in ("call", "raise", "bet"):
                    call_amt = min(tc, p.chips)
                    bet = p.place_bet(call_amt)
                    pot += bet
                    all_folded = False
            if record.bluff_attempted and all_folded:
                record.bluff_succeeded = True

        # Reset current_bet after pre-flop before any post-flop streets
        for p in active:
            p.current_bet = 0

        # ── POST-FLOP ──
        for street_name, n_cards in [("flop", 3), ("turn", 1), ("river", 1)]:
            survivors = [p for p in active if not p.folded]
            if len(survivors) < 2:
                break

            new_cards = deck.draw(n_cards)
            community.extend(new_cards if isinstance(new_cards, list) else [new_cards])

            # Reset current_bet at start of each new street
            for p in active:
                p.current_bet = 0

            if self.bot.folded:
                continue

            # --- Opponents act first; track the current street bet ---
            street_bet = 0  # highest bet on this street so far
            for p in survivors:
                if p is self.bot or p.folded or p.chips == 0:
                    continue
                tc = max(street_bet - p.current_bet, 0)
                tc = min(tc, p.chips)
                if hasattr(p, 'decide') and p.is_bot:
                    score_p, _, _ = evaluate_hand(p.hole_cards, community)
                    str_p = hand_strength_percentile(score_p) if score_p else random.uniform(0.3, 0.7)
                    action, amt = p.decide(tc, pot, self.bb, street_name, community, str_p)
                else:
                    action, amt = "check", 0

                if action == "fold":
                    p.folded = True
                elif action in ("bet", "raise"):
                    total = min(amt, p.chips)
                    bet = p.place_bet(total)
                    pot += bet
                    street_bet = p.current_bet
                elif action == "call" and tc > 0:
                    bet = p.place_bet(tc)
                    pot += bet
                self.strategy.record_postflop_action(p.name, action)

            if self.bot.folded:
                continue

            # Bot acts post-flop — faces real to_call
            to_call_bot = max(street_bet - self.bot.current_bet, 0)
            to_call_bot = min(to_call_bot, self.bot.chips)

            # Reset per-street current_bet for bot (it only contributed blinds pre-flop)
            score, cls, hand_name = evaluate_hand(self.bot.hole_cards, community)
            strength = hand_strength_percentile(score) if score else 0.4

            bot_pf_action, bot_pf_amt = self.strategy.postflop_decision(
                self.bot.hole_cards, community, pot, to_call_bot, self.bb,
                street_name, len([p for p in survivors if not p.folded]), position
            )
            self.strategy.flush_log()

            if bot_pf_action == "fold":
                self.bot.folded = True
                break
            elif bot_pf_action in ("bet", "raise"):
                if strength < 0.45:
                    record.bluff_attempted = True
                # bot_pf_amt is total chips to put in; must at least cover to_call_bot
                total = min(max(bot_pf_amt, to_call_bot), self.bot.chips)
                bet = self.bot.place_bet(total)
                pot += bet
                # Opponents respond to bot's bet
                new_street_bet = self.bot.current_bet
                all_folded_postflop = True
                for p in survivors:
                    if p is self.bot or p.folded or p.chips == 0:
                        continue
                    tc2 = max(new_street_bet - p.current_bet, 0)
                    tc2 = min(tc2, p.chips)
                    if tc2 <= 0:
                        all_folded_postflop = False
                        continue
                    score_p, _, _ = evaluate_hand(p.hole_cards, community)
                    str_p = hand_strength_percentile(score_p) if score_p else random.uniform(0.3, 0.7)
                    action2, _ = p.decide(tc2, pot, self.bb, street_name, community, str_p)
                    if action2 == "fold":
                        p.folded = True
                    else:
                        bet2 = p.place_bet(tc2)
                        pot += bet2
                        all_folded_postflop = False
                if all_folded_postflop and strength < 0.45:
                    record.bluff_succeeded = True
            elif bot_pf_action == "call" and to_call_bot > 0:
                bet = self.bot.place_bet(to_call_bot)
                pot += bet
            # else check — do nothing

        # ── SHOWDOWN / AWARD ──
        record.community_cards = cards_str_short(community) if community else "—"
        survivors = [p for p in active if not p.folded]

        if self.bot in survivors:
            score, cls, hand_name = evaluate_hand(self.bot.hole_cards, community) if community else (None, None, "Pre-flop")
            record.final_hand_name = hand_name
            record.final_hand_strength = hand_strength_percentile(score) if score else eq

            if len(survivors) == 1:
                # Everyone else folded — bot wins uncontested
                self.bot.chips += pot
                record.pot_won = pot
                if record.bluff_attempted:
                    record.bluff_succeeded = True
            else:
                # Showdown
                record.reached_showdown = True
                best_score = None
                winner = None
                for p in survivors:
                    s, _, _ = evaluate_hand(p.hole_cards, community) if community else (9999, None, None)
                    if s is None: s = 9999
                    if best_score is None or s < best_score:
                        best_score = s
                        winner = p
                if winner is self.bot:
                    record.won_at_showdown = True
                    self.bot.chips += pot
                    record.pot_won = pot
                else:
                    winner.chips += pot
        elif len(survivors) == 1:
            survivors[0].chips += pot

        record.bot_chips_end = self.bot.chips
        self.dealer_idx = (self.dealer_idx + 1) % len(active)
        return record


    def _get_position(self, active, bot, bb_idx):
        n = len(active)
        bot_idx = active.index(bot)
        distance = (bot_idx - bb_idx) % n
        if distance <= n // 3:
            return 0  # early
        elif distance <= 2 * n // 3:
            return 1  # mid
        else:
            return 2  # late


# ─────────────────────────────────────────────────────────────
# Run simulation
# ─────────────────────────────────────────────────────────────
def run_simulation(num_hands=1000, num_players=5, starting_chips=None,
                   big_blind=20, opponent_pool=None, verbose=True):

    if opponent_pool is None:
        opponent_pool = ["TAG", "LAG", "FISH", "ROCK", "random"]

    # 100BB is the standard cash game stack size.
    # Per-hand reset keeps each hand independent and bounds pot sizes.
    stack = 100 * big_blind
    if starting_chips is not None:
        stack = starting_chips

    # Build players
    our_bot = Player(name="PokerBot", chips=stack)
    our_bot._is_our_bot = True
    our_bot.is_bot = False

    ai_names = ["Alice","Bob","Carlos","Diana","Ethan","Fiona","George","Hannah"]
    random.shuffle(ai_names)

    players = [our_bot]
    for i in range(num_players - 1):
        arch = opponent_pool[i % len(opponent_pool)]
        ai = AIOpponent(name=ai_names[i % len(ai_names)], chips=stack, archetype=arch)
        players.append(ai)

    random.shuffle(players)

    strategy = AdaptiveStrategy(num_players=num_players)
    for p in players:
        if not getattr(p, '_is_our_bot', False):
            strategy.register_opponent(p.name)

    engine = HeadlessEngine(
        players=players,
        small_blind=big_blind // 2,
        big_blind=big_blind,
        strategy=strategy,
        bot_player=our_bot
    )

    records: List[HandRecord] = []

    if verbose:
        print(f"\n  Running {num_hands:,} hands ({num_players} players, BB={big_blind}, stack={stack}={stack//big_blind}BB)...")
        milestones = {num_hands // 4, num_hands // 2, 3 * num_hands // 4}

    bot_rebuys = 0
    for h in range(num_hands):
        # Rebuy any busted player (including bot) to keep simulation running.
        # Bot rebuys are tracked separately so chip trajectory stays honest —
        # each rebuy resets the baseline, not the cumulative record.
        for p in players:
            if p.chips <= 0:
                p.chips = stack
                if p is our_bot:
                    bot_rebuys += 1

        rec = engine.play_hand()
        if rec:
            records.append(rec)

        if verbose and (h + 1) in milestones:
            pct = int((h + 1) / num_hands * 100)
            print(f"  {pct}% complete ({h+1:,} hands)...")

    if verbose and bot_rebuys:
        print(f"  ⚠  Bot rebuyed {bot_rebuys}x (each rebuy = -100BB in real terms)")

    return records, strategy


# ─────────────────────────────────────────────────────────────
# Analysis & Report
# ─────────────────────────────────────────────────────────────
def analyze(records: List[HandRecord], strategy: AdaptiveStrategy, bb: int):
    n = len(records)
    if n == 0:
        print("No records to analyze.")
        return {}

    total_bb_delta = sum(r.bb_delta for r in records)
    bb_per_100 = (total_bb_delta / n) * 100

    showdown_records = [r for r in records if r.reached_showdown]
    showdown_wins = [r for r in showdown_records if r.won_at_showdown]
    showdown_win_pct = len(showdown_wins) / max(len(showdown_records), 1)

    bluff_attempts = [r for r in records if r.bluff_attempted]
    bluff_successes = [r for r in bluff_attempts if r.bluff_succeeded]
    bluff_success_pct = len(bluff_successes) / max(len(bluff_attempts), 1)

    preflop_folds = [r for r in records if r.preflop_action == "fold"]
    preflop_raises = [r for r in records if r.preflop_action in ("raise", "bet")]
    preflop_calls = [r for r in records if r.preflop_action == "call"]
    vpip = (len(preflop_raises) + len(preflop_calls)) / n
    pfr = len(preflop_raises) / n

    hands_won = [r for r in records if r.pot_won > 0]
    win_pct = len(hands_won) / n

    # Rolling BB/100 in windows of 100
    window = 100
    rolling = []
    for i in range(window, n + 1, window):
        chunk = records[i - window:i]
        # Sum bb_delta over the window then scale to per-100 rate
        rolling_bb100 = (sum(r.bb_delta for r in chunk) / window) * 100
        rolling.append((i, rolling_bb100))

    # Cumulative chip trajectory
    cumulative = []
    running = 0
    for r in records:
        running += r.chip_delta
        cumulative.append(running)

    return {
        "num_hands": n,
        "bb_per_100": bb_per_100,
        "total_chips_won": sum(r.chip_delta for r in records),
        "win_pct": win_pct,
        "showdown_win_pct": showdown_win_pct,
        "showdown_count": len(showdown_records),
        "bluff_attempts": len(bluff_attempts),
        "bluff_success_pct": bluff_success_pct,
        "vpip": vpip,
        "pfr": pfr,
        "preflop_folds": len(preflop_folds),
        "preflop_raises": len(preflop_raises),
        "preflop_calls": len(preflop_calls),
        "rolling_bb100": rolling,
        "cumulative_chips": cumulative,
        "records": records,
    }


def print_report(stats: dict, strategy: AdaptiveStrategy):
    print(f"""
╔══════════════════════════════════════════════════════╗
║              📊  SIMULATION REPORT                   ║
╚══════════════════════════════════════════════════════╝

  Hands Played       : {stats['num_hands']:,}
  ─────────────────────────────────────────
  BB/100 Win Rate    : {stats['bb_per_100']:+.2f}  {'✅ Winning' if stats['bb_per_100'] > 0 else '❌ Losing'}
  Total Chips Won    : {stats['total_chips_won']:+,}
  Win Rate (any pot) : {stats['win_pct']:.1%}
  ─────────────────────────────────────────
  Showdowns Reached  : {stats['showdown_count']:,}  ({stats['showdown_count']/stats['num_hands']:.1%} of hands)
  Showdown Win %     : {stats['showdown_win_pct']:.1%}
  ─────────────────────────────────────────
  Bluff Attempts     : {stats['bluff_attempts']:,}  ({stats['bluff_attempts']/stats['num_hands']:.1%} of hands)
  Bluff Success %    : {stats['bluff_success_pct']:.1%}
  ─────────────────────────────────────────
  VPIP (hands played): {stats['vpip']:.1%}
  PFR  (hands raised): {stats['pfr']:.1%}
  PF Folds           : {stats['preflop_folds']:,}
  PF Calls           : {stats['preflop_calls']:,}
  PF Raises          : {stats['preflop_raises']:,}
""")
    print(strategy.print_opponent_reads())

    # Rolling BB/100
    if stats['rolling_bb100']:
        print("\n  📈 Rolling BB/100 (per 100 hands):")
        for hand_n, bb100 in stats['rolling_bb100'][:10]:
            bar_len = int(abs(bb100) / 2)
            bar = ("+" if bb100 >= 0 else "-") * min(bar_len, 30)
            print(f"    Hand {hand_n:>5}: {bb100:+6.1f} BB/100  {bar}")
        if len(stats['rolling_bb100']) > 10:
            print(f"    ... ({len(stats['rolling_bb100'])} windows total, see chart)")


def save_csv(records: List[HandRecord], path="simulation_results.csv"):
    if not records:
        return
    fieldnames = [f for f in HandRecord.__dataclass_fields__] + ["chip_delta", "bb_delta"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            row = asdict(r)
            row["chip_delta"] = r.chip_delta
            row["bb_delta"] = round(r.bb_delta, 4)
            writer.writerow(row)
    print(f"\n  💾 Results saved to {path}")


def save_chart(stats: dict, path="win_rate_chart.png"):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec

        cumulative = stats["cumulative_chips"]
        rolling = stats["rolling_bb100"]
        n = stats["num_hands"]

        fig = plt.figure(figsize=(13, 8), facecolor="#1a1a2e")
        gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.4, wspace=0.35)

        # ── Chart 1: Cumulative chips ──
        ax1 = fig.add_subplot(gs[0, :])
        ax1.set_facecolor("#16213e")
        x = list(range(1, len(cumulative) + 1))
        color = ["#00d4aa" if v >= 0 else "#ff6b6b" for v in cumulative]
        ax1.fill_between(x, cumulative, 0,
                         where=[v >= 0 for v in cumulative], alpha=0.25, color="#00d4aa")
        ax1.fill_between(x, cumulative, 0,
                         where=[v < 0 for v in cumulative], alpha=0.25, color="#ff6b6b")
        ax1.plot(x, cumulative, color="#00d4aa", linewidth=1.2, alpha=0.9)
        ax1.axhline(0, color="#888", linewidth=0.8, linestyle="--")
        ax1.set_title("Cumulative Chip P&L", color="white", fontsize=13, pad=10)
        ax1.set_xlabel("Hand #", color="#aaa")
        ax1.set_ylabel("Chips", color="#aaa")
        ax1.tick_params(colors="#aaa")
        for spine in ax1.spines.values():
            spine.set_edgecolor("#444")

        # ── Chart 2: Rolling BB/100 ──
        ax2 = fig.add_subplot(gs[1, 0])
        ax2.set_facecolor("#16213e")
        if rolling:
            rx = [r[0] for r in rolling]
            ry = [r[1] for r in rolling]
            bar_colors = ["#00d4aa" if v >= 0 else "#ff6b6b" for v in ry]
            ax2.bar(rx, ry, width=80, color=bar_colors, alpha=0.85)
            ax2.axhline(0, color="#888", linewidth=0.8)
            avg = stats["bb_per_100"]
            ax2.axhline(avg, color="#f9ca24", linewidth=1.5, linestyle="--",
                        label=f"Avg {avg:+.1f} BB/100")
            ax2.legend(fontsize=8, labelcolor="white", facecolor="#1a1a2e")
        ax2.set_title("Rolling BB/100", color="white", fontsize=11, pad=8)
        ax2.set_xlabel("Hand #", color="#aaa")
        ax2.set_ylabel("BB/100", color="#aaa")
        ax2.tick_params(colors="#aaa")
        for spine in ax2.spines.values():
            spine.set_edgecolor("#444")

        # ── Chart 3: Strategy breakdown pie ──
        ax3 = fig.add_subplot(gs[1, 1])
        ax3.set_facecolor("#16213e")
        labels = ["Folds", "Calls", "Raises"]
        sizes = [stats["preflop_folds"], stats["preflop_calls"], stats["preflop_raises"]]
        colors = ["#ff6b6b", "#f9ca24", "#00d4aa"]
        wedges, texts, autotexts = ax3.pie(
            sizes, labels=labels, colors=colors,
            autopct="%1.1f%%", startangle=90,
            textprops={"color": "white", "fontsize": 9}
        )
        for at in autotexts:
            at.set_color("white")
        ax3.set_title("Pre-flop Actions", color="white", fontsize=11, pad=8)

        # Stats box
        stats_text = (
            f"BB/100: {stats['bb_per_100']:+.2f}\n"
            f"VPIP: {stats['vpip']:.1%}  PFR: {stats['pfr']:.1%}\n"
            f"SD Win: {stats['showdown_win_pct']:.1%}\n"
            f"Bluff: {stats['bluff_success_pct']:.1%} success\n"
            f"Hands: {n:,}"
        )
        fig.text(0.5, 0.01, stats_text, ha="center", va="bottom",
                 color="#aaa", fontsize=9,
                 bbox=dict(boxstyle="round,pad=0.4", facecolor="#16213e", edgecolor="#444"))

        plt.suptitle("🃏 Poker Bot Strategy Benchmark", color="white",
                     fontsize=15, fontweight="bold", y=1.01)

        plt.savefig(path, dpi=150, bbox_inches="tight", facecolor="#1a1a2e")
        plt.close()
        print(f"  📊 Chart saved to {path}")
    except Exception as e:
        print(f"  ⚠  Chart generation failed: {e}")


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════╗
║        🔬  POKER BOT BENCHMARK SIMULATOR             ║
╚══════════════════════════════════════════════════════╝
""")
    try:
        num_hands = int(input("  Hands to simulate [default 2000]: ").strip() or "2000")
    except ValueError:
        num_hands = 2000

    try:
        num_players = int(input("  Players at table (3-9) [default 5]: ").strip() or "5")
        num_players = max(3, min(9, num_players))
    except ValueError:
        num_players = 5

    try:
        big_blind = int(input("  Big blind [default 20]: ").strip() or "20")
    except ValueError:
        big_blind = 20

    print("\n  Opponent mix: TAG, LAG, FISH, ROCK (random mix)")

    records, strategy = run_simulation(
        num_hands=num_hands,
        num_players=num_players,
        big_blind=big_blind,
        verbose=True
    )

    stats = analyze(records, strategy, big_blind)
    print_report(stats, strategy)
    save_csv(records, "simulation_results.csv")
    save_chart(stats, "win_rate_chart.png")