"""
Adaptive poker strategy engine.
Core philosophy:
  - Pre-flop: enter pots with hands that have equity or implied odds
  - Post-flop: think in ranges, not just own hand strength.
    When opponent raises, ask: "what % of their range beats me?"
    If that % is low enough given pot odds, we call or re-raise.
  - Never fold strong hands just because someone bet big.
    A big bet could be a bluff — punish it with good hands.
"""
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from treys import Card
from hand_evaluator import (
    estimate_preflop_strength, hand_strength_percentile,
    detect_draws, evaluate_hand
)

# ---------------------------------------------------------------------------
# Opponent Model
# ---------------------------------------------------------------------------
@dataclass
class OpponentStats:
    name: str
    hands_seen: int = 0
    vpip: int = 0
    pfr: int = 0
    aggression_bets: int = 0
    aggression_calls: int = 0
    folds_to_3bet: int = 0
    faced_3bet: int = 0
    preflop_bet_sizes: List[float] = field(default_factory=list)
    fold_to_cbet: int = 0
    faced_cbet: int = 0
    showdown_hands: List[float] = field(default_factory=list)

    @property
    def vpip_pct(self):
        return self.vpip / max(self.hands_seen, 1)

    @property
    def pfr_pct(self):
        return self.pfr / max(self.hands_seen, 1)

    @property
    def aggression_factor(self):
        return self.aggression_bets / max(self.aggression_calls, 1)

    @property
    def avg_preflop_bet_pct(self):
        return sum(self.preflop_bet_sizes) / max(len(self.preflop_bet_sizes), 1)

    @property
    def fold_to_3bet_pct(self):
        return self.folds_to_3bet / max(self.faced_3bet, 1)

    @property
    def fold_to_cbet_pct(self):
        return self.fold_to_cbet / max(self.faced_cbet, 1)

    def archetype(self):
        vpip = self.vpip_pct
        pfr  = self.pfr_pct
        af   = self.aggression_factor
        if vpip < 0.20 and pfr > 0.15:   return "TAG"
        elif vpip < 0.20:                  return "ROCK"
        elif vpip > 0.40 and af > 2:       return "LAG"
        elif vpip > 0.40:                  return "FISH"
        else:                              return "UNKNOWN"

    def bluff_frequency(self):
        """Estimate how often this opponent bluffs when raising.
        LAGs bluff often (~40%), TAGs occasionally (~20%), FISHes rarely (~10%).
        More aggression bets relative to calls = more likely bluffing.
        """
        arch = self.archetype()
        base = {"LAG": 0.40, "TAG": 0.20, "FISH": 0.10, "ROCK": 0.08}.get(arch, 0.25)
        # Adjust upward if they have high AF (lots of bets/raises vs calls)
        af_bonus = min((self.aggression_factor - 1.0) * 0.05, 0.15)
        return min(base + af_bonus, 0.55)

    def range_ahead_of(self, our_strength):
        """
        Given our hand strength (0-1 percentile), estimate what fraction
        of this opponent's betting range actually beats us.
        A LAG raises with a wide range so less of it beats strong hands.
        A ROCK only raises with the top 10% so more of it beats us.
        """
        arch = self.archetype()
        # Approximate: how tight is their value range when raising?
        # ROCK raises top 10% → if our strength > 0.90 we're ahead of most
        # LAG raises top 40% → if our strength > 0.60 we're ahead of much of range
        range_width = {"ROCK": 0.10, "TAG": 0.20, "UNKNOWN": 0.28,
                       "FISH": 0.35, "LAG": 0.42}.get(arch, 0.25)
        # Fraction of their range that beats us = how far into range_width our strength sits
        # If strength = 0.80 and range_width = 0.20, then most of range is below us
        if our_strength >= (1.0 - range_width * 0.5):
            return 0.15  # we beat most of their range
        elif our_strength >= (1.0 - range_width):
            return 0.40  # roughly even with their range
        else:
            return 0.70  # most of their range beats us


# ---------------------------------------------------------------------------
# Hand category helpers
# ---------------------------------------------------------------------------
RANK_STR = "23456789TJQKA"

def get_hole_card_ranks(hole_cards):
    r = sorted([RANK_STR[Card.get_rank_int(c)] for c in hole_cards],
               key=lambda x: RANK_STR.index(x), reverse=True)
    return tuple(r)

def get_hole_suited(hole_cards):
    return Card.get_suit_int(hole_cards[0]) == Card.get_suit_int(hole_cards[1])

def hand_category(hole_cards):
    ranks  = get_hole_card_ranks(hole_cards)
    suited = get_hole_suited(hole_cards)
    r0, r1 = ranks
    gap     = abs(RANK_STR.index(r0) - RANK_STR.index(r1))
    is_pair = r0 == r1
    pair_rank = RANK_STR.index(r0) if is_pair else -1

    if is_pair and pair_rank >= 9: return 'premium'   # JJ+
    if r0 == 'A' and r1 == 'K':   return 'premium'
    if r0 == 'A' and r1 == 'Q' and suited: return 'premium'

    if is_pair and pair_rank >= 7: return 'strong'    # 99-TT
    if r0 == 'A' and r1 in ('Q','J'): return 'strong'
    if r0 == 'A' and r1 == 'T' and suited: return 'strong'
    if r0 == 'K' and r1 == 'Q':   return 'strong'
    if r0 == 'K' and r1 == 'J' and suited: return 'strong'

    if is_pair:                    return 'speculative'   # 22-88
    if suited and gap <= 2 and RANK_STR.index(r1) >= 3: return 'speculative'
    if r0 == 'A' and suited:       return 'speculative'
    if r0 in ('K','Q') and r1 in ('J','T') and suited: return 'speculative'

    if r0 == 'A' and RANK_STR.index(r1) >= 4: return 'marginal'
    if r0 in ('K','Q') and r1 in ('J','T'):    return 'marginal'

    return 'trash'


# ---------------------------------------------------------------------------
# Board texture
# ---------------------------------------------------------------------------
def board_texture(community_cards):
    if not community_cards:
        return {}
    suits = [Card.get_suit_int(c) for c in community_cards]
    ranks = sorted([Card.get_rank_int(c) for c in community_cards])
    suit_counts = {s: suits.count(s) for s in set(suits)}
    max_suit = max(suit_counts.values())
    rank_counts = {}
    for r in ranks:
        rank_counts[r] = rank_counts.get(r, 0) + 1
    paired_board = any(v >= 2 for v in rank_counts.values())
    unique_ranks  = sorted(set(ranks))
    connected = any(
        unique_ranks[i+2] - unique_ranks[i] <= 4
        for i in range(len(unique_ranks) - 2)
    ) if len(unique_ranks) >= 3 else False
    high_card = any(r >= 9 for r in ranks)   # T+ on board
    return {
        "flush_draw_board": max_suit >= 3,
        "monotone":         max_suit == len(community_cards),
        "paired":           paired_board,
        "connected":        connected,
        "high_card":        high_card,
        "dry":              not connected and max_suit < 3 and not paired_board,
    }


def best_case_strength(strength, draws, board, street):
    boost = 0.0
    if draws.get("flush_draw"):
        boost += 0.18 if street == "flop" else 0.09
    if draws.get("straight_draw"):
        boost += 0.14 if street == "flop" else 0.07
    if draws.get("backdoor_flush") and street == "flop":
        boost += 0.05
    return min(strength + boost, 1.0)

def worst_case_strength(strength, draws, board, street):
    discount = 0.0
    if board.get("flush_draw_board"):  discount += 0.05
    if board.get("connected"):         discount += 0.04
    if street == "flop":               discount += 0.03
    elif street == "turn":             discount += 0.015
    return max(strength - discount, 0.0)

def is_pot_committed(invested, pot):
    return invested > 0 and (invested / max(pot, 1)) > 0.28


# ---------------------------------------------------------------------------
# Core Strategy
# ---------------------------------------------------------------------------
class AdaptiveStrategy:
    def __init__(self, num_players: int):
        self.num_players   = num_players
        self.opponents: Dict[str, OpponentStats] = {}
        self.hand_count    = 0
        self.position      = 0
        self.is_preflop_aggressor = False
        self.bluff_budget  = 0.0
        self._log: List[str] = []
        self._hand_invested = 0
        self._last_raiser   = None   # track who raised last for range reads

    def log(self, msg): self._log.append(msg)
    def flush_log(self):
        msgs = self._log[:]
        self._log.clear()
        return msgs

    def register_opponent(self, name):
        if name not in self.opponents:
            self.opponents[name] = OpponentStats(name=name)

    def record_preflop_action(self, name, action, bet_amount, big_blind, faced_raise=False):
        if name not in self.opponents:
            self.register_opponent(name)
        opp = self.opponents[name]
        opp.hands_seen += 1
        if action in ("call","raise","bet"):
            opp.vpip += 1
            if bet_amount > 0:
                opp.preflop_bet_sizes.append((bet_amount / max(big_blind,1)) * 100)
        if action == "raise":
            opp.pfr += 1
            opp.aggression_bets += 1
            self._last_raiser = name
        elif action == "call":
            opp.aggression_calls += 1
        elif action == "bet":
            opp.aggression_bets += 1
            self._last_raiser = name
        elif action == "fold" and faced_raise:
            opp.folds_to_3bet += 1
        if faced_raise:
            opp.faced_3bet += 1

    def record_postflop_action(self, name, action, faced_cbet=False):
        if name not in self.opponents:
            return
        opp = self.opponents[name]
        if action in ("bet","raise"):
            opp.aggression_bets += 1
            self._last_raiser = name
        elif action == "call":
            opp.aggression_calls += 1
        if faced_cbet:
            opp.faced_cbet += 1
            if action == "fold":
                opp.fold_to_cbet += 1

    # ------------------------------------------------------------------
    # PRE-FLOP
    # ------------------------------------------------------------------
    def preflop_decision(self, hole_cards, pot, to_call, big_blind,
                         position, num_active, raises_so_far, limpers):
        self.position = position
        self.hand_count += 1
        self.bluff_budget = random.random()
        self.is_preflop_aggressor = False
        self._hand_invested = 0
        self._last_raiser = None

        equity    = estimate_preflop_strength(hole_cards)
        category  = hand_category(hole_cards)
        suited    = get_hole_suited(hole_cards)
        ranks     = get_hole_card_ranks(hole_cards)

        open_thresh  = self._open_raise_equity_threshold(num_active, position)
        # call_thresh only slightly looser than open — 3% gap means we need real equity to enter
        call_thresh  = open_thresh - 0.03
        raise_size   = self._compute_open_raise(big_blind, limpers, self._table_vpip_avg())

        self.log(f" PF | cat={category} eq={equity:.2f} thresh={open_thresh:.2f} pos={['EP','MP','LP'][position]} raises={raises_so_far}")

        # ── Facing 3-bet or more ──
        if raises_so_far >= 2:
            if category == 'premium' or equity > 0.63:
                self.is_preflop_aggressor = True
                self.log(" → 4-bet, premium vs 3-bet")
                return "raise", min(to_call * 3, pot)
            # Strong hands: don't fold, call and see a flop
            if category == 'strong' and to_call <= big_blind * 6:
                self.log(" → Calling 3-bet, strong hand")
                self._hand_invested += to_call
                return "call", to_call
            if equity > 0.55 and to_call <= big_blind * 4:
                self.log(" → Calling 3-bet, decent equity")
                self._hand_invested += to_call
                return "call", to_call
            self.log(" → Folding to 3-bet")
            return "fold", 0

        # ── Facing single raise ──
        elif raises_so_far == 1:
            # Always 3-bet premiums and strong hands in position
            if category == 'premium':
                self.is_preflop_aggressor = True
                self.log(" → 3-bet premium")
                return "raise", to_call * 3
            if category == 'strong' and position >= 1:
                self.is_preflop_aggressor = True
                self.log(" → 3-bet strong in position")
                return "raise", to_call * 3

            # Light 3-bet vs foldable opponent
            target = self._most_foldable_raiser()
            if target and position == 2 and self.bluff_budget > 0.80:
                self.is_preflop_aggressor = True
                self.log(f" → Light 3-bet bluff vs {target}")
                return "raise", to_call * 3

            # Call raise only with real equity and a reasonable price
            if equity >= call_thresh and to_call <= big_blind * 3:
                self.log(" → Calling raise")
                self._hand_invested += to_call
                return "call", to_call
            # Speculative hands: only call if very cheap and in position (set mining, suited connectors)
            if category == 'speculative' and position >= 1 and to_call <= big_blind * 2:
                self.log(" → Calling raise, speculative implied odds")
                self._hand_invested += to_call
                return "call", to_call

            self.log(" → Folding to raise")
            return "fold", 0

        # ── Unraised pot ──
        else:
            if limpers >= 2 and position >= 1 and equity > 0.56:
                amount = big_blind * (3 + limpers)
                self.is_preflop_aggressor = True
                self.log(f" → Squeeze vs {limpers} limpers")
                return "raise", amount

            if equity >= open_thresh or category in ('premium','strong'):
                self.is_preflop_aggressor = True
                self.log(f" → Opening raise {raise_size}")
                self._hand_invested += raise_size
                return "raise", raise_size

            # Limp speculative only in position when there are already limpers (good implied odds)
            if category == 'speculative' and position >= 1 and limpers >= 1 and to_call <= big_blind:
                self.log(" → Limping speculative in position")
                self._hand_invested += to_call
                return "call", to_call

            # Complete BB only with hands that have real value — not just marginal equity
            if to_call == 0:
                return "check", 0

            if category in ('strong', 'speculative') and equity >= call_thresh and to_call <= big_blind:
                self.log(" → Completing BB with playable hand")
                self._hand_invested += to_call
                return "call", to_call

            if position == 2 and self.bluff_budget > 0.75 and limpers == 0:
                self.is_preflop_aggressor = True
                self.log(" → Stealing blinds")
                return "raise", int(big_blind * 2.5)

            self.log(" → Folding pre-flop")
            return "fold", 0

    # ------------------------------------------------------------------
    # POST-FLOP
    # ------------------------------------------------------------------
    def postflop_decision(self, hole_cards, community_cards, pot,
                          to_call, big_blind, street, num_active, position):
        """
        Key insight: when an opponent bets/raises, we don't just compare
        our hand to a fixed threshold. We ask:
          1. What fraction of their range actually beats us? (range_ahead)
          2. What are our pot odds? (pot_odds)
          3. If range_ahead < pot_odds, calling is +EV — even if they
             sometimes have us crushed, the times they're bluffing or
             have a worse hand make calling profitable.
          4. If we have a very strong hand (top pair+), re-raise to
             punish bluffs and build value — don't just call with monsters.
        """
        score, cls, hand_name = evaluate_hand(hole_cards, community_cards)
        strength = hand_strength_percentile(score) if score else 0.4
        draws    = detect_draws(hole_cards, community_cards)
        board    = board_texture(community_cards)

        best      = best_case_strength(strength, draws, board, street)
        worst     = worst_case_strength(strength, draws, board, street)
        ev_str    = (strength * 0.60) + (best * 0.25) + (worst * 0.15)

        pot_odds  = to_call / (pot + to_call) if (pot + to_call) > 0 else 0
        has_draw  = draws["flush_draw"] or draws["straight_draw"] or draws["backdoor_flush"]
        committed = is_pot_committed(self._hand_invested, pot + to_call)

        # Figure out who raised and how likely they're bluffing
        raiser_opp   = self.opponents.get(self._last_raiser) if self._last_raiser else None
        bluff_freq   = raiser_opp.bluff_frequency() if raiser_opp else 0.25
        range_ahead  = raiser_opp.range_ahead_of(strength) if raiser_opp else (1.0 - strength)

        # Effective equity against their range:
        # When they bluff (bluff_freq of the time) we almost always win.
        # When they have value (1-bluff_freq) we win based on strength vs their range.
        equity_vs_range = (bluff_freq * 0.85) + ((1 - bluff_freq) * (1.0 - range_ahead))
        # Blend with raw hand strength — raw strength is the floor
        effective_eq = max(equity_vs_range, strength * 0.5)

        self.log(
            f" [{street}] {hand_name} | str={strength:.2f} ev={ev_str:.2f} "
            f"pot_odds={pot_odds:.2f} bluff_freq={bluff_freq:.2f} "
            f"range_ahead={range_ahead:.2f} eff_eq={effective_eq:.2f} committed={committed}"
        )

        # ── Facing a bet ──
        if to_call > 0:

            # STRONG HAND vs raise → re-raise, don't just call
            # If we have top pair or better AND opponent could be bluffing, punish them
            if strength > 0.70 and effective_eq > 0.55:
                raise_amt = max(int(to_call * 2.5), big_blind * 2)
                self.log(f" → RE-RAISE strong hand {raise_amt} (str={strength:.2f}, bluff_freq={bluff_freq:.2f})")
                self._hand_invested += raise_amt
                return "raise", raise_amt

            # Good hand, clearly +EV call — opponent's range doesn't beat us enough
            if effective_eq > pot_odds + 0.08:
                self.log(f" → Call, +EV vs range (eff_eq={effective_eq:.2f} > {pot_odds:.2f}+0.08)")
                self._hand_invested += to_call
                return "call", to_call

            # Decent hand, marginal but still +EV — require more margin and stronger hand
            if effective_eq > pot_odds + 0.06 and strength > 0.50:
                self.log(f" → Thin call (eff_eq={effective_eq:.2f} > {pot_odds:.2f}+0.06)")
                self._hand_invested += to_call
                return "call", to_call

            # Pot committed — we've already put too much in to fold
            if committed and ev_str > pot_odds - 0.12:
                self.log(" → Pot committed, calling")
                self._hand_invested += to_call
                return "call", to_call

            # Draw call: correct odds to chase
            if has_draw and street != "river":
                draw_eq = 0.36 if draws["flush_draw"] else (0.30 if draws["straight_draw"] else 0.12)
                if draw_eq > pot_odds * 0.80:
                    self.log(f" → Draw call (draw_eq={draw_eq:.2f})")
                    self._hand_invested += to_call
                    return "call", to_call

            # Semi-bluff raise with strong draw
            if has_draw and street in ("flop","turn") and self.bluff_budget > 0.68:
                if draws["flush_draw"] or draws["straight_draw"]:
                    raise_amt = max(int(to_call * 2.2), big_blind * 2)
                    self.log(f" → Semi-bluff raise {raise_amt}")
                    self._hand_invested += raise_amt
                    return "raise", raise_amt

            # Hero call vs frequent bluffer — require meaningful hand strength
            if bluff_freq > 0.38 and strength > 0.55 and pot_odds < 0.40:
                self.log(f" → Hero call vs frequent bluffer (bluff={bluff_freq:.2f})")
                self._hand_invested += to_call
                return "call", to_call

            self.log(f" → Fold (eff_eq={effective_eq:.2f} < pot_odds={pot_odds:.2f})")
            return "fold", 0

        # ── No bet to face ──
        else:
            # Value bet sizing based on board texture
            if ev_str > 0.62:
                if board.get("dry"):
                    size_pct = 0.75
                elif board.get("flush_draw_board") or board.get("connected"):
                    size_pct = 0.55
                else:
                    size_pct = 0.65
                bet = max(int(pot * size_pct), big_blind)
                self.log(f" → Value bet {bet} ({size_pct:.0%} pot)")
                self._hand_invested += bet
                return "bet", bet

            # C-bet as pre-flop aggressor — need decent equity, not just any hand
            if self.is_preflop_aggressor and street == "flop":
                if ev_str > 0.48 or (has_draw and ev_str > 0.38):
                    cbet = max(int(pot * 0.50), big_blind)
                    self.log(f" → C-bet {cbet}")
                    self._hand_invested += cbet
                    return "bet", cbet
                if board.get("dry") and self.bluff_budget > 0.72:
                    cbet = max(int(pot * 0.40), big_blind)
                    self.log(f" → Bluff c-bet {cbet} dry board")
                    self._hand_invested += cbet
                    return "bet", cbet

            # Semi-bluff draws
            if has_draw and street in ("flop","turn"):
                if draws["flush_draw"] or draws["straight_draw"]:
                    if self.bluff_budget > 0.42:
                        bet = max(int(pot * 0.55), big_blind)
                        self.log(f" → Semi-bluff {bet}")
                        self._hand_invested += bet
                        return "bet", bet

            # Thin value / protection on turn and river
            if street in ("turn","river") and ev_str > 0.52:
                bet = max(int(pot * 0.50), big_blind)
                self.log(f" → Thin value bet {bet}")
                self._hand_invested += bet
                return "bet", bet

            # River bluff on scare cards
            if street == "river" and self.bluff_budget > 0.80:
                if board.get("flush_draw_board") or board.get("connected"):
                    bet = max(int(pot * 0.65), big_blind)
                    self.log(f" → River bluff {bet}")
                    self._hand_invested += bet
                    return "bet", bet

            self.log(" → Check")
            return "check", 0

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------
    def _open_raise_equity_threshold(self, num_active, position):
        """
        HU equity threshold for opening. estimate_preflop_strength() returns
        heads-up equity so these must be calibrated in that space.
        Target VPIP ~25-30%: tight enough to avoid leaking, loose enough to win.
        More players = tighter (more people to beat).
        """
        base = {
            2: 0.46, 3: 0.50, 4: 0.52, 5: 0.54,
            6: 0.55, 7: 0.56, 8: 0.57, 9: 0.58
        }.get(num_active, 0.54)
        # Late position opens wider — button is the most profitable seat
        pos_discount = [0.04, 0.02, 0.0][position]
        return base - pos_discount

    def _compute_open_raise(self, big_blind, limpers, table_looseness):
        base      = 2.5 if self.num_players <= 4 else 3.0
        limp_tax  = limpers * 1.0
        loose_tax = 0.5 if table_looseness > 0.35 else 0.0
        return int(big_blind * (base + limp_tax + loose_tax))

    def _table_vpip_avg(self):
        if not self.opponents:
            return 0.30
        return sum(o.vpip_pct for o in self.opponents.values()) / len(self.opponents)

    def _most_foldable_raiser(self):
        best, best_fold = None, 0.0
        for name, opp in self.opponents.items():
            if opp.faced_3bet >= 2 and opp.fold_to_3bet_pct > best_fold:
                best_fold = opp.fold_to_3bet_pct
                best = name
        return best if best and best_fold > 0.50 else None

    def print_opponent_reads(self):
        lines = ["\n📊 OPPONENT READS:"]
        for name, opp in self.opponents.items():
            lines.append(
                f"  {name:12s} | {opp.archetype():7s} | VPIP:{opp.vpip_pct:.0%} "
                f"PFR:{opp.pfr_pct:.0%} AF:{opp.aggression_factor:.1f} "
                f"bluff%:{opp.bluff_frequency():.0%} "
                f"F/3b:{opp.fold_to_3bet_pct:.0%} F/cb:{opp.fold_to_cbet_pct:.0%}"
            )
        return "\n".join(lines)