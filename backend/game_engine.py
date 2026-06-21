"""
Texas Hold'em Game Engine.
Handles the full hand lifecycle: deal → betting rounds → showdown.
"""
import random
from typing import List, Optional
from treys import Card, Deck, Evaluator

from players import Player, AIOpponent, HumanPlayer, cards_str, card_str
from hand_evaluator import evaluate_hand, hand_strength_percentile, rank_description

evaluator = Evaluator()
RANK_CLASS_NAMES = {
    1: "Royal Flush", 2: "Straight Flush", 3: "Four of a Kind",
    4: "Full House", 5: "Flush", 6: "Straight", 7: "Three of a Kind",
    8: "Two Pair", 9: "Pair", 10: "High Card"
}


class GameEngine:
    def __init__(self, players: List[Player], small_blind: int = 10,
                 big_blind: int = 20, adaptive_bot=None):
        self.players = players
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.adaptive_bot = adaptive_bot  # the strategy engine for our bot
        self.dealer_idx = 0
        self.hand_num = 0
        self.deck = None
        self.community_cards = []
        self.pot = 0
        self.side_pots = []

    # ------------------------------------------------------------------
    # MAIN HAND LOOP
    # ------------------------------------------------------------------
    def play_hand(self):
        self.hand_num += 1
        print(f"\n{'='*60}")
        print(f"  HAND #{self.hand_num}  |  Dealer: {self.players[self.dealer_idx].name}")
        print(f"{'='*60}")

        # Reset
        for p in self.players:
            p.reset_for_hand()
        self.community_cards = []
        self.pot = 0

        # Remove busted players
        active = [p for p in self.players if p.chips > 0]
        if len(active) < 2:
            print("Not enough players to continue.")
            return

        # Deal
        self.deck = Deck()
        self.deck.shuffle()
        for p in active:
            p.hole_cards = self.deck.draw(2)

        # Reveal our bot's cards
        our_bot = next((p for p in active if not p.is_human and not p.is_bot), None)
        human = next((p for p in active if p.is_human), None)

        if our_bot:
            print(f"\n  🤖 Your bot's hole cards: {rank_description(our_bot.hole_cards)}")
        if human:
            pass  # Human sees cards during their action

        # Post blinds
        sb_idx = (self.dealer_idx + 1) % len(active)
        bb_idx = (self.dealer_idx + 2) % len(active)
        sb_player = active[sb_idx]
        bb_player = active[bb_idx]

        sb_amount = sb_player.place_bet(self.small_blind)
        bb_amount = bb_player.place_bet(self.big_blind)
        self.pot += sb_amount + bb_amount
        print(f"\n  Blinds: {sb_player.name} posts SB ${sb_amount}, {bb_player.name} posts BB ${bb_amount}")

        # Pre-flop analysis window: observe everyone before our bot acts
        self._betting_round(active, start_idx=(bb_idx + 1) % len(active),
                            street="preflop", current_bet=self.big_blind,
                            bb_idx=bb_idx)

        # Flop
        survivors = [p for p in active if not p.folded]
        if len(survivors) < 2:
            self._award_pot(survivors)
            return
        self.community_cards = self.deck.draw(3)
        print(f"\n  🃏 FLOP: {cards_str(self.community_cards)}")
        self._betting_round(survivors, start_idx=sb_idx % len(survivors),
                            street="flop", current_bet=0)

        # Turn
        survivors = [p for p in active if not p.folded]
        if len(survivors) < 2:
            self._award_pot(survivors)
            return
        self.community_cards += self.deck.draw(1)
        print(f"\n  🃏 TURN: {cards_str(self.community_cards)}")
        self._betting_round(survivors, start_idx=sb_idx % len(survivors),
                            street="turn", current_bet=0)

        # River
        survivors = [p for p in active if not p.folded]
        if len(survivors) < 2:
            self._award_pot(survivors)
            return
        self.community_cards += self.deck.draw(1)
        print(f"\n  🃏 RIVER: {cards_str(self.community_cards)}")
        self._betting_round(survivors, start_idx=sb_idx % len(survivors),
                            street="river", current_bet=0)

        # Showdown
        survivors = [p for p in active if not p.folded]
        self._showdown(survivors)

        # Advance dealer
        self.dealer_idx = (self.dealer_idx + 1) % len([p for p in self.players if p.chips > 0])

    # ------------------------------------------------------------------
    # BETTING ROUND
    # ------------------------------------------------------------------
    def _betting_round(self, active_players, start_idx, street, current_bet, bb_idx=None):
        players = [p for p in active_players if not p.folded and not p.all_in]
        if not players:
            return

        # Reset current_bet contributions this street
        for p in active_players:
            p.current_bet = 0 if street != "preflop" else p.current_bet

        n = len(players)
        if n == 0:
            return

        acted = set()
        i = start_idx % n
        raises_so_far = 0
        limpers = 0  # for preflop analysis

        # Track pre-flop observations for opponent modeling
        preflop_actions = {}

        max_iters = n * 3  # safety cap
        iters = 0

        while iters < max_iters:
            iters += 1
            live = [p for p in players if not p.folded and not p.all_in and p.chips > 0]
            if not live:
                break
            i = i % len(live)
            p = live[i]

            to_call = current_bet - p.current_bet
            to_call = max(to_call, 0)
            to_call = min(to_call, p.chips)

            # Check if everyone has acted and bets are equal
            all_acted = len(acted) >= len(live)
            bets_equal = all(
                (x.current_bet == current_bet or x.folded or x.all_in or x.chips == 0)
                for x in live
            )
            if all_acted and bets_equal:
                break

            print(f"\n  [{street.upper()}] {p.name} | Chips: ${p.chips} | Pot: ${self.pot} | To call: ${to_call}")

            # Determine position (0=early, 1=mid, 2=late)
            position = 2 if i == len(live) - 1 else (1 if i >= len(live) // 2 else 0)

            action, amount = self._get_action(
                p, to_call, self.pot, self.big_blind, street,
                self.community_cards, position, raises_so_far, limpers, active_players
            )

            # Record for opponent modeling
            if street == "preflop" and self.adaptive_bot and not getattr(p, '_is_our_bot', False):
                if hasattr(p, 'is_bot') and p.is_bot or (hasattr(p, 'is_human') and p.is_human):
                    self.adaptive_bot.record_preflop_action(
                        p.name, action, amount if action in ("bet","raise") else to_call,
                        self.big_blind, faced_raise=raises_so_far > 0
                    )
            elif street != "preflop" and self.adaptive_bot:
                if hasattr(p, 'is_bot') and p.is_bot:
                    self.adaptive_bot.record_postflop_action(p.name, action)

            # Apply action
            if action == "fold":
                p.folded = True
                print(f"  ✗ {p.name} folds")
            elif action in ("call", "check"):
                bet = p.place_bet(to_call)
                self.pot += bet
                if to_call > 0:
                    print(f"  → {p.name} calls ${bet}")
                    if street == "preflop":
                        limpers += 1
                else:
                    print(f"  → {p.name} checks")
            elif action in ("bet", "raise"):
                # Amount is total, above current_bet
                total = amount + to_call if action == "raise" else amount
                total = max(total, current_bet + self.big_blind)  # min raise
                total = min(total, p.chips)
                bet = p.place_bet(total)
                self.pot += bet
                current_bet = p.current_bet
                raises_so_far += 1
                print(f"  ↑ {p.name} {'raises' if action=='raise' else 'bets'} to ${current_bet} (total pot: ${self.pot})")
                # Reset acted so everyone has to respond
                acted = {p.name}
            elif action == "all-in":
                bet = p.place_bet(p.chips)
                self.pot += bet
                p.all_in = True
                if p.current_bet > current_bet:
                    current_bet = p.current_bet
                    raises_so_far += 1
                print(f"  💥 {p.name} is ALL-IN for ${bet}!")

            acted.add(p.name)
            i = (i + 1) % max(len([x for x in live if not x.folded and not x.all_in]), 1)

        # Print strategy logs for our bot
        if self.adaptive_bot:
            for msg in self.adaptive_bot.flush_log():
                print(f"  🧠{msg}")

    # ------------------------------------------------------------------
    # GET ACTION from a player
    # ------------------------------------------------------------------
    def _get_action(self, player, to_call, pot, big_blind, street,
                    community, position, raises_so_far, limpers, all_players):
        if player.is_human:
            score, cls, hand_name = evaluate_hand(player.hole_cards, community)
            return player.decide(to_call, pot, big_blind, street, community, hand_name)

        elif hasattr(player, '_is_our_bot') and player._is_our_bot:
            # Our adaptive strategy bot
            num_active = len([p for p in all_players if not p.folded])
            if street == "preflop":
                return self.adaptive_bot.preflop_decision(
                    player.hole_cards, pot, to_call, big_blind,
                    position, num_active, raises_so_far, limpers
                )
            else:
                score, cls, hand_name = evaluate_hand(player.hole_cards, community)
                return self.adaptive_bot.postflop_decision(
                    player.hole_cards, community, pot, to_call,
                    big_blind, street, num_active, position
                )

        elif hasattr(player, 'decide') and player.is_bot:
            # Simple AI opponent
            score, cls, hand_name = evaluate_hand(player.hole_cards, community)
            strength = hand_strength_percentile(score) if score else random.uniform(0.3, 0.7)
            return player.decide(to_call, pot, big_blind, street, community, strength)

        return "fold", 0

    # ------------------------------------------------------------------
    # SHOWDOWN
    # ------------------------------------------------------------------
    def _showdown(self, survivors):
        print(f"\n  {'─'*50}")
        print(f"  🏆 SHOWDOWN  (Pot: ${self.pot})")
        
        best_score = None
        winner = None
        
        for p in survivors:
            score, cls, hand_name = evaluate_hand(p.hole_cards, self.community_cards)
            if score is None:
                score = 9999
            print(f"  {p.name}: {rank_description(p.hole_cards)} → {hand_name} (score: {score})")
            if best_score is None or score < best_score:
                best_score = score
                winner = p

        self._award_pot([winner])

    def _award_pot(self, winners):
        if not winners:
            return
        share = self.pot // len(winners)
        for w in winners:
            w.chips += share
            print(f"\n  🏅 {w.name} wins ${share}!")
        self.pot = 0


# ------------------------------------------------------------------
# CHIP SUMMARY
# ------------------------------------------------------------------
def print_chip_counts(players):
    print(f"\n  {'─'*40}")
    print("  CHIP COUNTS:")
    for p in sorted(players, key=lambda x: -x.chips):
        bar = "█" * (p.chips // 100)
        print(f"    {p.name:14s} ${p.chips:>6}  {bar}")
    print(f"  {'─'*40}")
