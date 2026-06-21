"""
Player classes: Human (CLI), Simple AI opponents, and our AdaptiveBot.
"""
import random
from dataclasses import dataclass, field
from typing import List, Optional
from treys import Card


def card_str(card):
    ranks = ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]
    suits = {1: "♠", 2: "♥", 4: "♦", 8: "♣"}
    r = Card.get_rank_int(card)
    s = Card.get_suit_int(card)
    return ranks[r] + suits.get(s, "?")

def cards_str(cards):
    return " ".join(card_str(c) for c in cards)


@dataclass
class Player:
    name: str
    chips: int
    is_bot: bool = False
    is_human: bool = False
    hole_cards: List = field(default_factory=list)
    current_bet: int = 0
    folded: bool = False
    all_in: bool = False
    position_index: int = 0  # seat index at table

    def reset_for_hand(self):
        self.hole_cards = []
        self.current_bet = 0
        self.folded = False
        self.all_in = False

    def place_bet(self, amount):
        amount = min(amount, self.chips)
        self.chips -= amount
        self.current_bet += amount
        return amount

    def __repr__(self):
        return f"{self.name}(${self.chips})"


# ---------------------------------------------------------------------------
# AI Opponent — Simple archetype-based player
# ---------------------------------------------------------------------------
class AIOpponent(Player):
    def __init__(self, name, chips, archetype="random"):
        super().__init__(name=name, chips=chips, is_bot=True)
        self.archetype = archetype  # TAG, LAG, FISH, ROCK, random

    def decide(self, to_call, pot, big_blind, street, community_cards, hand_strength=None):
        """Returns (action, amount). Simple heuristic AI."""
        arch = self.archetype
        if arch == "random":
            arch = random.choice(["TAG", "LAG", "FISH", "ROCK"])

        # Generate looseness/aggression based on archetype
        if arch == "ROCK":
            call_thresh, raise_thresh, bluff_prob = 0.70, 0.80, 0.03
        elif arch == "TAG":
            call_thresh, raise_thresh, bluff_prob = 0.55, 0.65, 0.08
        elif arch == "LAG":
            call_thresh, raise_thresh, bluff_prob = 0.40, 0.50, 0.20
        else:  # FISH
            call_thresh, raise_thresh, bluff_prob = 0.30, 0.70, 0.05

        strength = hand_strength or random.uniform(0.35, 0.75)
        bluffing = random.random() < bluff_prob

        if to_call == 0:
            if strength > raise_thresh or bluffing:
                amount = max(int(pot * random.uniform(0.4, 0.8)), big_blind)
                return "bet", amount
            return "check", 0
        else:
            if strength > raise_thresh or bluffing:
                amount = int(to_call * random.uniform(2.0, 3.5))
                return "raise", amount
            elif strength > call_thresh:
                return "call", to_call
            else:
                return "fold", 0


# ---------------------------------------------------------------------------
# Human Player — CLI prompts
# ---------------------------------------------------------------------------
class HumanPlayer(Player):
    def __init__(self, name, chips):
        super().__init__(name=name, chips=chips, is_human=True)

    def decide(self, to_call, pot, big_blind, street, community_cards, hand_name=None):
        from hand_evaluator import rank_description
        print(f"\n  🃏 Your hand: {rank_description(self.hole_cards)}", end="")
        if hand_name:
            print(f"  [{hand_name}]", end="")
        print()
        if community_cards:
            print(f"  Board: {cards_str(community_cards)}")
        print(f"  Pot: ${pot}  |  Your chips: ${self.chips}")
        if to_call > 0:
            print(f"  To call: ${to_call}")

        options = []
        if to_call == 0:
            options = ["check", "bet", "fold"]
            prompt = "  Action [check/bet/fold]: "
        else:
            options = ["call", "raise", "fold"]
            prompt = "  Action [call/raise/fold]: "

        while True:
            action = input(prompt).strip().lower()
            if action in options:
                break
            print(f"  ⚠  Please choose from: {', '.join(options)}")

        amount = 0
        if action in ("bet", "raise"):
            while True:
                try:
                    amount = int(input(f"  Amount (min {max(to_call*2, big_blind)}): ").strip())
                    if amount >= max(to_call * 2 if to_call else big_blind, 1):
                        break
                    print("  ⚠  Amount too small.")
                except ValueError:
                    print("  ⚠  Enter a number.")
        elif action == "call":
            amount = to_call

        return action, amount
