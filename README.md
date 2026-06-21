# 🃏 Adaptive Poker Bot

A Texas Hold'em AI that doesn't just play poker — it *studies* you, adapts to your tendencies, and tries to take your chips. Built with a FastAPI WebSocket backend, a React frontend, and a strategy engine that models opponents in real time.

To play the game: https://poker-bot-ruddy.vercel.app/

---

## What It Does

- **Full Texas Hold'em** — pre-flop through showdown, blinds, all-ins, side pots
- **Adaptive AI bot** that tracks opponent VPIP, PFR, aggression factor, and fold tendencies
- **Monte Carlo equity estimation** to calculate hand strength pre-flop
- **Draw detection** — flush draws, straight draws, backdoor draws
- **Bluffing, c-bets, squeeze plays, blind steals** — the full toolkit
- **Play or spectate** — jump in yourself or just watch the bot go to work
- **Live brain feed** — see exactly what the bot is thinking on every street
- **Opponent reads** — TAG, LAG, FISH, ROCK classifications that update hand by hand

---

## Tech Stack

| Layer | Tech |
|---|---|
| Frontend | React + Vite |
| Backend | FastAPI + WebSockets |
| Hand evaluation | [treys](https://github.com/ihendley/treys) |
| Deployment | Vercel (frontend) + Railway (backend) |

---

## Project Structure

```
poker_bot/
├── backend/
│   ├── server.py          # FastAPI WebSocket server
│   ├── game_engine.py     # Hand lifecycle: deal → showdown
│   ├── strategy.py        # Adaptive bot brain
│   ├── hand_evaluator.py  # Hand classification + equity
│   ├── players.py         # Player classes (bot, human, AI)
│   ├── simulate.py        # Run bulk simulations + stats
│   └── main.py            # CLI mode (no browser needed)
└── frontend/
    └── src/
        └── App.jsx        # Full React UI
```

---

## Running Locally

**Backend** (Terminal 1):
```bash
cd backend
pip install fastapi uvicorn treys
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

**Frontend** (Terminal 2):
```bash
cd frontend
npm install
npm run dev
```

Then open `http://localhost:5173` and deal yourself in.

**CLI mode** (no browser, just vibes):
```bash
cd backend
python main.py
```

---

## Simulation Mode

Want to run 2,000 hands and see how the bot performs?

```bash
cd backend
python simulate.py
```

Outputs BB/100, VPIP, PFR, showdown win %, and bluff success rate. Saves a CSV and chart to your project folder.

**Target stats for a well-tuned bot:**

| Metric | Target |
|---|---|
| VPIP | 25–35% |
| PFR | 15–22% |
| SD Win | > 50% |
| Bluff success | 50–60% |

---

## How the Bot Thinks

**Pre-flop:** Monte Carlo simulates 300 random boards to estimate equity. Raises, calls, folds, and occasional blind steals based on position + table looseness.

**Post-flop:** Evaluates best 5-card hand from all 7 cards (fixed treys off-by-one bug), calculates pot odds, detects draws, decides whether to value bet, bluff, c-bet, or check.

**Opponent modeling:** Every action is recorded. After a few hands the bot knows who folds to 3-bets, who's a calling station, and who's just gambling.

TAG, LAG, FISH, ROCK. Bot classifies each player and adjusts accordingly.

TAG — tight and aggressive, only plays strong hands but bets them hard

LAG — plays a wide range, applies constant pressure

FISH — loose passive, calls everything, rarely raises

ROCK — only comes alive with the nuts, folds everything else

(I personally go LAG to TAG)

---

## Deployment

| Service | What it hosts | URL |
|---|---|---|
| Railway | FastAPI backend | `wss://your-app.up.railway.app/ws` |
| Vercel | React frontend | `https://your-app.vercel.app` |

**Railway free tier:** ~$5 credit/month. Light usage costs $1–3/month.

---

## What's Next (maybe)

- [ ] Side pot handling for multi-way all-ins
- [ ] Hand history replay
- [ ] Leaderboard across sessions
- [ ] GTO range charts overlay

---

*Built hand by hand. Bugs fixed card by card.* 🂡
