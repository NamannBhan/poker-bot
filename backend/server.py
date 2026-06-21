"""
FastAPI + WebSocket backend for the Poker Bot UI.
Supports both watch mode (bot only) and play mode (human + bot).
"""
import sys, os, random, asyncio, json, traceback
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from treys import Card, Deck, Evaluator

from players import Player, AIOpponent
from strategy import AdaptiveStrategy
from hand_evaluator import (
    evaluate_hand, hand_strength_percentile,
    estimate_preflop_strength, detect_draws
)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def card_to_dict(card):
    ranks = "23456789TJQKA"
    suit_map = {1:"spades",2:"hearts",4:"diamonds",8:"clubs"}
    suit_sym = {1:"♠",2:"♥",4:"♦",8:"♣"}
    r = Card.get_rank_int(card)
    s = Card.get_suit_int(card)
    return {"rank": ranks[r], "suit": suit_map.get(s,"?"),
            "suit_sym": suit_sym.get(s,"?"),
            "display": ranks[r] + suit_sym.get(s,"?"),
            "color": "red" if s in (2,4) else "white", "raw": card}

def cards_to_list(cards):
    return [card_to_dict(c) for c in cards] if cards else []


class PokerGame:
    def __init__(self):
        self.reset()

    def reset(self):
        self.players = []
        self.strategy = None
        self.our_bot = None
        self.human_player = None
        self.community_cards = []
        self.pot = 0
        self.hand_num = 0
        self.dealer_idx = 0
        self.big_blind = 20
        self.small_blind = 10
        self.stats = {
            "hands_played": 0, "hands_won": 0, "bb_won": 0.0,
            "vpip": 0, "pfr": 0, "bluff_attempts": 0,
            "bluff_successes": 0, "showdowns": 0, "showdown_wins": 0,
        }

    def setup(self, num_players, big_blind, starting_chips, human_name=None):
        self.reset()
        self.big_blind = big_blind
        self.small_blind = big_blind // 2

        self.our_bot = Player(name="PokerBot", chips=starting_chips)
        self.our_bot._is_our_bot = True
        self.our_bot.is_bot = False
        self.our_bot.is_human = False
        self.players.append(self.our_bot)

        if human_name:
            h = Player(name=human_name, chips=starting_chips)
            h.is_human = True
            h.is_bot = False
            h._is_our_bot = False
            self.human_player = h
            self.players.append(h)

        names = ["Alice","Bob","Carlos","Diana","Ethan","Fiona","George","Hannah"]
        archs = ["TAG","LAG","FISH","ROCK","TAG","LAG","FISH","ROCK"]
        random.shuffle(names)
        ai_count = num_players - 1 - (1 if human_name else 0)
        for i in range(ai_count):
            ai = AIOpponent(name=names[i], chips=starting_chips, archetype=archs[i % len(archs)])
            self.players.append(ai)

        random.shuffle(self.players)
        self.strategy = AdaptiveStrategy(num_players=num_players)
        for p in self.players:
            if not getattr(p, '_is_our_bot', False) and not getattr(p, 'is_human', False):
                self.strategy.register_opponent(p.name)

    def get_state(self, showdown=False):
        return {
            "players": [
                self._showdown_player_state(p) if showdown else self._player_state(p)
                for p in self.players
            ],
            "community_cards": cards_to_list(self.community_cards),
            "pot": self.pot,
            "hand_num": self.hand_num,
            "big_blind": self.big_blind,
            "stats": self.stats,
            "opponent_reads": self._opponent_reads(),
            "dealer_idx": self.dealer_idx,
        }

    def _player_state(self, p):
        is_our_bot = getattr(p, '_is_our_bot', False)
        is_human = getattr(p, 'is_human', False)
        human_at_table = self.human_player is not None
        show = is_human or (is_our_bot and not human_at_table)
        return {
            "name": p.name,
            "chips": p.chips,
            "folded": p.folded,
            "all_in": p.all_in,
            "current_bet": p.current_bet,
            "is_bot": is_our_bot,
            "is_human": is_human,
            "hole_cards": cards_to_list(p.hole_cards) if (show and p.hole_cards) else [],
            "hole_cards_hidden": len(p.hole_cards) > 0 and not show,
        }

    def _showdown_player_state(self, p):
        """At showdown, reveal hole cards only for non-folded players."""
        is_our_bot = getattr(p, '_is_our_bot', False)
        is_human = getattr(p, 'is_human', False)
        # Only reveal cards if the player didn't fold — folded hands stay hidden
        reveal = not p.folded and p.hole_cards
        return {
            "name": p.name,
            "chips": p.chips,
            "folded": p.folded,
            "all_in": p.all_in,
            "current_bet": p.current_bet,
            "is_bot": is_our_bot,
            "is_human": is_human,
            "hole_cards": cards_to_list(p.hole_cards) if reveal else [],
            "hole_cards_hidden": False,
        }

    def _opponent_reads(self):
        if not self.strategy:
            return []
        out = []
        for name, opp in self.strategy.opponents.items():
            out.append({
                "name": name, "archetype": opp.archetype(),
                "vpip": round(opp.vpip_pct * 100, 1),
                "pfr": round(opp.pfr_pct * 100, 1),
                "aggression_factor": round(opp.aggression_factor, 2),
                "avg_bet_pct_bb": round(opp.avg_preflop_bet_pct, 1),
                "fold_to_3bet": round(opp.fold_to_3bet_pct * 100, 1),
                "hands_seen": opp.hands_seen,
            })
        return out


game = PokerGame()


async def stream(ws, event_type, data={}):
    await ws.send_json({"type": event_type, **data})
    await asyncio.sleep(0.35)


async def run_hand(ws: WebSocket, action_queue: asyncio.Queue):
    g = game
    g.hand_num += 1
    g.stats["hands_played"] += 1

    for p in g.players:
        p.reset_for_hand()
    g.community_cards = []
    g.pot = 0

    active = [p for p in g.players if p.chips > 0]
    if len(active) < 2:
        await stream(ws, "game_over", {"message": "Not enough players!"})
        return

    deck = Deck()
    deck.shuffle()
    for p in active:
        drawn = deck.draw(2)
        p.hole_cards = drawn if isinstance(drawn, list) else [drawn]

    bot_chips_start = g.our_bot.chips

    await stream(ws, "hand_start", {"hand_num": g.hand_num, "state": g.get_state()})

    sb_idx = (g.dealer_idx + 1) % len(active)
    bb_idx = (g.dealer_idx + 2) % len(active)
    sb_p, bb_p = active[sb_idx], active[bb_idx]
    g.pot += sb_p.place_bet(g.small_blind) + bb_p.place_bet(g.big_blind)

    await stream(ws, "blinds_posted", {
        "sb": sb_p.name, "bb": bb_p.name,
        "sb_amount": g.small_blind, "bb_amount": g.big_blind,
        "pot": g.pot, "state": g.get_state()
    })

    # ── BETTING ROUND ─────────────────────────────────────────────────────────
    async def betting_round(street, start_idx, current_bet, community):
        live = [p for p in active if not p.folded and not p.all_in and p.chips > 0]
        if not live:
            return current_bet
        for p in active:
            if street != "preflop":
                p.current_bet = 0

        limpers, raises = 0, 0
        acted = set()
        i = start_idx % len(live)
        iters = 0

        while iters < len(live) * 3:
            iters += 1
            live = [p for p in active if not p.folded and not p.all_in and p.chips > 0]
            if not live:
                break
            i = i % len(live)
            p = live[i]

            to_call = max(current_bet - p.current_bet, 0)
            to_call = min(to_call, p.chips)
            bets_equal = all(
                x.current_bet == current_bet or x.folded or x.all_in or x.chips == 0
                for x in live
            )
            if len(acted) >= len(live) and bets_equal:
                break

            position = 2 if i == len(live)-1 else (1 if i >= len(live)//2 else 0)
            num_active = len([x for x in active if not x.folded])
            action, amount = "fold", 0

            # ── OUR BOT ──
            if getattr(p, '_is_our_bot', False):
                if street == "preflop":
                    action, amount = g.strategy.preflop_decision(
                        p.hole_cards, g.pot, to_call, g.big_blind,
                        position, num_active, raises, limpers)
                    eq = estimate_preflop_strength(p.hole_cards)
                    if action in ("raise","bet") and eq < 0.50:
                        g.stats["bluff_attempts"] += 1
                    if action in ("raise","bet","call"):
                        g.stats["vpip"] += 1
                    if action in ("raise","bet"):
                        g.stats["pfr"] += 1
                else:
                    score, cls, _ = evaluate_hand(p.hole_cards, community)
                    strength = hand_strength_percentile(score) if score else 0.4
                    action, amount = g.strategy.postflop_decision(
                        p.hole_cards, community, g.pot, to_call,
                        g.big_blind, street, num_active, position)
                    if action in ("raise","bet") and strength < 0.45:
                        g.stats["bluff_attempts"] += 1

                brain_logs = g.strategy.flush_log()
                eq = estimate_preflop_strength(p.hole_cards) if street == "preflop" else \
                     hand_strength_percentile(evaluate_hand(p.hole_cards, community)[0] or 9999)
                draws = detect_draws(p.hole_cards, community) if community else {}
                pot_odds = to_call / (g.pot + to_call) if (g.pot + to_call) > 0 else 0

                await stream(ws, "bot_thinking", {
                    "logs": brain_logs,
                    "equity": round(eq * 100, 1),
                    "pot_odds": round(pot_odds * 100, 1),
                    "has_flush_draw": draws.get("flush_draw", False),
                    "has_straight_draw": draws.get("straight_draw", False),
                    "action": action, "amount": amount,
                })

            # ── HUMAN PLAYER ──
            elif getattr(p, 'is_human', False):
                score, cls, hand_name = evaluate_hand(p.hole_cards, community) if community else (None, None, "High Card")
                await ws.send_json({
                    "type": "human_turn",
                    "to_call": to_call,
                    "pot": g.pot,
                    "chips": p.chips,
                    "hand_cards": cards_to_list(p.hole_cards),
                    "hand_name": hand_name or "High Card",
                    "community": cards_to_list(community),
                    "min_raise": max(to_call * 2, g.big_blind),
                    "big_blind": g.big_blind,
                    "state": g.get_state(),
                })
                # Wait for the human to click a button (comes via action_queue)
                resp = await action_queue.get()
                action = resp.get("action", "fold")
                amount = resp.get("amount", 0)

            # ── AI OPPONENT ──
            elif getattr(p, 'is_bot', False):
                score, cls, _ = evaluate_hand(p.hole_cards, community)
                strength = hand_strength_percentile(score) if score else random.uniform(0.3, 0.7)
                action, amount = p.decide(to_call, g.pot, g.big_blind, street, community, strength)
                if street == "preflop":
                    g.strategy.record_preflop_action(
                        p.name, action,
                        amount if action in ("bet","raise") else to_call,
                        g.big_blind, raises > 0)
                else:
                    g.strategy.record_postflop_action(p.name, action)

            # ── APPLY ACTION ──
            if action == "fold":
                p.folded = True
            elif action == "check":
                pass
            elif action == "call":
                bet = p.place_bet(to_call)
                g.pot += bet
                if street == "preflop":
                    limpers += 1
            elif action in ("bet", "raise"):
                total = min(max(amount + to_call, current_bet + g.big_blind), p.chips)
                bet = p.place_bet(total)
                g.pot += bet
                current_bet = p.current_bet
                raises += 1
                acted = {p.name}
            elif action == "all-in":
                bet = p.place_bet(p.chips)
                g.pot += bet
                p.all_in = True
                if p.current_bet > current_bet:
                    current_bet = p.current_bet
                    raises += 1

            acted.add(p.name)

            await stream(ws, "player_action", {
                "player": p.name,
                "action": action,
                "amount": p.current_bet if action in ("bet","raise","call","all-in") else 0,
                "pot": g.pot,
                "is_bot": getattr(p, '_is_our_bot', False),
                "is_human": getattr(p, 'is_human', False),
            })

            live_next = [x for x in live if not x.folded and not x.all_in and x.chips > 0]
            i = (i + 1) % max(len(live_next), 1)

        return current_bet

    # ── STREETS ───────────────────────────────────────────────────────────────
    await betting_round("preflop", (bb_idx+1) % len(active), g.big_blind, [])

    for street_name, n_cards in [("flop", 3), ("turn", 1), ("river", 1)]:
        survivors = [p for p in active if not p.folded]
        if len(survivors) < 2:
            break
        drawn = deck.draw(n_cards)
        new_cards = drawn if isinstance(drawn, list) else [drawn]
        g.community_cards.extend(new_cards)
        await stream(ws, "street", {
            "street": street_name,
            "new_cards": cards_to_list(new_cards),
            "all_cards": cards_to_list(g.community_cards),
            "state": g.get_state()
        })
        await betting_round(street_name, sb_idx % len(survivors), 0, g.community_cards)

    # ── SHOWDOWN ──────────────────────────────────────────────────────────────
    survivors = [p for p in active if not p.folded]
    showdown_data = []
    best_score, winner = None, None

    for p in survivors:
        score, cls, hand_name = evaluate_hand(p.hole_cards, g.community_cards) if g.community_cards else (None, None, "High Card")
        if score is None:
            score = 9999
        showdown_data.append({
            "name": p.name, "cards": cards_to_list(p.hole_cards),
            "hand_name": hand_name, "score": score,
            "is_bot": getattr(p, '_is_our_bot', False),
            "is_human": getattr(p, 'is_human', False),
        })
        if best_score is None or score < best_score:
            best_score, winner = score, p

    if len(survivors) > 1:
        g.stats["showdowns"] += 1
        if winner is g.our_bot:
            g.stats["showdown_wins"] += 1

    if winner:
        winner.chips += g.pot
        if winner is g.our_bot:
            g.stats["hands_won"] += 1

    chip_delta = g.our_bot.chips - bot_chips_start
    g.stats["bb_won"] += chip_delta / g.big_blind

    await stream(ws, "showdown", {
        "players": showdown_data,
        "winner": winner.name if winner else "—",
        "pot": g.pot,
        "chip_delta": chip_delta,
        "state": g.get_state(showdown=True),
    })

    g.pot = 0
    g.dealer_idx = (g.dealer_idx + 1) % len([p for p in g.players if p.chips > 0])


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    global game
    action_queue = asyncio.Queue()
    hand_task = None

    try:
        while True:
            msg = await ws.receive_json()
            cmd = msg.get("cmd")

            if cmd == "setup":
                game.setup(
                    num_players=msg.get("num_players", 5),
                    big_blind=msg.get("big_blind", 20),
                    starting_chips=msg.get("starting_chips", 1000),
                    human_name=msg.get("human_name"),
                )
                await ws.send_json({"type": "ready", "state": game.get_state()})

            elif cmd == "deal":
                async def run_and_complete():
                    await run_hand(ws, action_queue)
                    await ws.send_json({"type": "hand_complete", "state": game.get_state()})
                hand_task = asyncio.create_task(run_and_complete())

            elif cmd == "human_action":
                await action_queue.put({
                    "action": msg.get("action", "fold"),
                    "amount": msg.get("amount", 0),
                })

            elif cmd == "get_state":
                await ws.send_json({"type": "state", "state": game.get_state()})

    except WebSocketDisconnect:
        if hand_task:
            hand_task.cancel()
    except Exception as e:
        tb = traceback.format_exc()
        print(f"\n❌ ERROR:\n{tb}")
        if hand_task:
            hand_task.cancel()
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except:
            pass


@app.get("/")
def root():
    return {"status": "Poker Bot API running"}