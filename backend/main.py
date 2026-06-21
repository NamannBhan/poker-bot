"""
🃏 Adaptive Poker Bot — Main Entry Point

Texas Hold'em with:
- Configurable number of players (3-9 including you)
- Our adaptive AI bot that models opponents and adjusts strategy
- Simple AI opponents with different archetypes
- Full hand lifecycle: pre-flop through showdown
"""
import random
import sys
from players import Player, AIOpponent, HumanPlayer
from game_engine import GameEngine, print_chip_counts
from strategy import AdaptiveStrategy

ARCHETYPES = ["TAG", "LAG", "FISH", "ROCK", "random"]

BANNER = """
╔══════════════════════════════════════════════════════╗
║           🃏  ADAPTIVE POKER BOT  🃏                 ║
║         Texas Hold'em with AI Strategy               ║
╚══════════════════════════════════════════════════════╝
"""


def setup_game():
    print(BANNER)

    # Number of players
    while True:
        try:
            n = int(input("  How many players at the table? (3-9, including you and our bot): ").strip())
            if 3 <= n <= 9:
                break
            print("  ⚠  Must be between 3 and 9.")
        except ValueError:
            print("  ⚠  Enter a number.")

    # Play mode
    print("\n  Who are you?")
    print("  [1] I want to WATCH the bot play (bot vs AI opponents)")
    print("  [2] I want to PLAY against the bot and AI opponents")
    choice = input("  Choice [1/2]: ").strip()
    human_plays = choice == "2"

    # Starting chips
    try:
        starting_chips = int(input("\n  Starting chips per player [default 1000]: ").strip() or "1000")
    except ValueError:
        starting_chips = 1000

    # Blinds
    try:
        big_blind = int(input("  Big blind amount [default 20]: ").strip() or "20")
    except ValueError:
        big_blind = 20
    small_blind = big_blind // 2

    print(f"\n  Setting up {n}-player table | Blinds: {small_blind}/{big_blind} | Starting chips: ${starting_chips}")
    print()

    # Build player list
    players = []

    # Our adaptive bot
    our_bot = Player(name="🤖 PokerBot", chips=starting_chips)
    our_bot._is_our_bot = True
    our_bot.is_bot = False
    players.append(our_bot)

    # Human player (optional)
    human_count = 1 if human_plays else 0
    if human_plays:
        name = input("  Your name: ").strip() or "Human"
        human = HumanPlayer(name=name, chips=starting_chips)
        players.append(human)

    # Fill rest with AI opponents
    ai_names = ["Alice", "Bob", "Carlos", "Diana", "Ethan",
                "Fiona", "George", "Hannah"]
    random.shuffle(ai_names)
    ai_needed = n - 1 - human_count  # -1 for our bot

    for i in range(ai_needed):
        arch = random.choice(ARCHETYPES)
        ai = AIOpponent(name=ai_names[i], chips=starting_chips, archetype=arch)
        players.append(ai)
        print(f"  + AI opponent: {ai_names[i]:8s} [style: {arch}]")

    random.shuffle(players)

    # Create strategy engine
    strategy = AdaptiveStrategy(num_players=n)
    for p in players:
        if not getattr(p, '_is_our_bot', False):
            strategy.register_opponent(p.name)

    # Create game engine
    engine = GameEngine(
        players=players,
        small_blind=small_blind,
        big_blind=big_blind,
        adaptive_bot=strategy
    )

    return engine, strategy, our_bot


def main():
    engine, strategy, our_bot = setup_game()

    print(f"\n  ✅ Game ready! {len(engine.players)} players.\n")
    input("  Press ENTER to start playing...\n")

    hand_num = 0
    max_hands = None

    try:
        n_str = input("  How many hands to play? [Enter for unlimited]: ").strip()
        if n_str:
            max_hands = int(n_str)
    except ValueError:
        max_hands = None

    print()

    while True:
        # Check for bust-outs
        active = [p for p in engine.players if p.chips > 0]
        if len(active) < 2:
            print("\n  Game over — not enough players with chips!")
            break

        hand_num += 1
        if max_hands and hand_num > max_hands:
            print(f"\n  Played {max_hands} hands. Game over!")
            break

        # Check if our bot is bust
        if our_bot.chips <= 0:
            print(f"\n  💀 PokerBot is out of chips after {hand_num-1} hands!")
            break

        engine.play_hand()
        print_chip_counts(engine.players)

        # Print opponent reads every 5 hands
        if hand_num % 5 == 0:
            print(strategy.print_opponent_reads())

        # Pause between hands
        response = input("\n  [ENTER] next hand | [q] quit | [r] show reads: ").strip().lower()
        if response == "q":
            break
        if response == "r":
            print(strategy.print_opponent_reads())

    # Final summary
    print(f"\n{'='*60}")
    print("  FINAL STANDINGS")
    print(f"{'='*60}")
    print_chip_counts(engine.players)
    print(strategy.print_opponent_reads())
    print(f"\n  Thanks for playing! 🃏")


if __name__ == "__main__":
    main()
