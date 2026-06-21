"""
Hand evaluation using treys library.
Provides utilities for hand strength, equity estimation, and draw detection.
"""
from treys import Card, Evaluator, Deck
import random

evaluator = Evaluator()

# Treys uses 0-based class integers (0=Royal Flush ... 9=High Card)
RANK_CLASS_NAMES = {
    0: "Royal Flush", 1: "Straight Flush", 2: "Four of a Kind",
    3: "Full House",  4: "Flush",          5: "Straight",
    6: "Three of a Kind", 7: "Two Pair",   8: "Pair", 9: "High Card"
}

def make_card(rank, suit):
    """rank: '2'-'9','T','J','Q','K','A'  suit: 's','h','d','c'"""
    return Card.new(rank + suit)

def evaluate_hand(hole_cards, community_cards):
    """Returns (score, class_int, class_name). Lower score = stronger hand."""
    if len(community_cards) < 3:
        return None, None, "Pre-flop"
    score = evaluator.evaluate(community_cards, hole_cards)
    cls = evaluator.get_rank_class(score)
    return score, cls, RANK_CLASS_NAMES.get(cls, "Unknown")

def hand_strength_percentile(score):
    """Convert raw score to win percentile (0-1, higher = better)."""
    if score is None:
        return 0.5
    # treys scores: 1 (best) to 7462 (worst)
    return 1.0 - (score / 7462.0)

def estimate_preflop_strength(hole_cards):
    """
    Monte Carlo equity estimation pre-flop.
    Returns win probability (0-1).
    """
    wins = 0
    trials = 300
    deck_cards = Deck.GetFullDeck()
    # Remove hole cards from deck
    available = [c for c in deck_cards if c not in hole_cards]

    for _ in range(trials):
        sample = random.sample(available, 7)  # 5 community + 2 opponent
        community = sample[:5]
        opp_hole = sample[5:]
        my_score = evaluator.evaluate(community, hole_cards)
        opp_score = evaluator.evaluate(community, opp_hole)
        if my_score < opp_score:
            wins += 1
        elif my_score == opp_score:
            wins += 0.5

    return wins / trials

def detect_draws(hole_cards, community_cards):
    """Detect flush draws and open-ended straight draws."""
    if len(community_cards) < 3:
        return {"flush_draw": False, "straight_draw": False, "backdoor_flush": False}

    all_cards = hole_cards + community_cards
    
    # Flush draw: exactly 4 cards of same suit (one away from a flush)
    # Note: >= 5 means the flush is already made (handled by evaluate_hand)
    suits = [Card.get_suit_int(c) for c in all_cards]
    suit_counts = {s: suits.count(s) for s in set(suits)}
    flush_draw = any(cnt == 4 for cnt in suit_counts.values())
    backdoor_flush = any(cnt == 3 for cnt in suit_counts.values()) and len(community_cards) == 3

    # Straight draw: find ranks
    ranks = sorted(set(Card.get_rank_int(c) for c in all_cards))
    # Check for 4 consecutive ranks (OESD)
    straight_draw = False
    for i in range(len(ranks) - 3):
        window = ranks[i:i+4]
        if window[-1] - window[0] == 3:
            straight_draw = True
            break

    return {
        "flush_draw": flush_draw,
        "straight_draw": straight_draw,
        "backdoor_flush": backdoor_flush
    }

def rank_description(hole_cards):
    """Get a human-readable description of hole cards."""
    r1 = Card.get_rank_int(hole_cards[0])
    r2 = Card.get_rank_int(hole_cards[1])
    s1 = Card.get_suit_int(hole_cards[0])
    s2 = Card.get_suit_int(hole_cards[1])
    
    ranks = ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]
    suits_sym = {1: "♠", 2: "♥", 4: "♦", 8: "♣"}
    
    r1_str = ranks[r1] + suits_sym.get(s1, "?")
    r2_str = ranks[r2] + suits_sym.get(s2, "?")
    return f"{r1_str} {r2_str}"