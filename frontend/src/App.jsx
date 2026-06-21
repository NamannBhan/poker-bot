import { useState, useEffect, useRef, useCallback } from "react";

const C = {
  felt: "#0a3d22", feltMid: "#0d4a2a", feltRim: "#083018",
  navy: "#060d1f", navyMid: "#0b1530",
  gold: "#c9a84c", white: "#f0ede4", dimText: "#8a9ab0",
  red: "#e05252", green: "#38c97a", blue: "#4a9eff", purple: "#9b7fe8",
  bark: "#1a2e1a",
};

const suitColor = s => (s === "hearts" || s === "diamonds") ? "#d0302a" : "#111111";

// ─── Card ────────────────────────────────────────────────────────────────────
function Card({ card, hidden, small, glow }) {
  if (!card && !hidden) return null;
  const w = small ? 36 : 52, h = small ? 50 : 72;
  if (hidden) return (
    <div style={{
      width: w, height: h, borderRadius: 6, flexShrink: 0,
      border: "1px solid #1a3a2a", boxShadow: "0 2px 8px #00000066",
      background: "repeating-linear-gradient(135deg,#0d2a18 0,#0d2a18 4px,#0a2014 4px,#0a2014 8px)",
    }} />
  );
  return (
    <div style={{
      width: w, height: h, borderRadius: 6, background: "#f7f3eb", flexShrink: 0,
      border: glow ? `2px solid ${C.gold}` : "1px solid #2a4a2a",
      boxShadow: glow ? `0 0 12px ${C.gold}88` : "0 2px 8px #00000066",
      display: "flex", flexDirection: "column", justifyContent: "space-between",
      padding: "3px 4px",
    }}>
      <div style={{ fontSize: small ? 10 : 13, fontWeight: 700, color: suitColor(card.suit), fontFamily: "monospace", lineHeight: 1 }}>{card.rank}</div>
      <div style={{ fontSize: small ? 13 : 20, textAlign: "center", color: suitColor(card.suit), lineHeight: 1 }}>{card.suit_sym}</div>
      <div style={{ fontSize: small ? 10 : 13, fontWeight: 700, color: suitColor(card.suit), alignSelf: "flex-end", transform: "rotate(180deg)", fontFamily: "monospace", lineHeight: 1 }}>{card.rank}</div>
    </div>
  );
}

// ─── Chip Bar ────────────────────────────────────────────────────────────────
function ChipBar({ chips, max }) {
  const pct = Math.min(chips / max, 1);
  return (
    <div style={{ width: "100%", height: 4, background: "#0a1a0a", borderRadius: 2 }}>
      <div style={{ width: `${pct * 100}%`, height: "100%", borderRadius: 2, transition: "width 0.5s",
        background: pct > 0.6 ? C.green : pct > 0.3 ? C.gold : C.red }} />
    </div>
  );
}

// ─── Player Seat ─────────────────────────────────────────────────────────────
function PlayerSeat({ player, isDealer, startChips, isYourTurn }) {
  const isBot = player.is_bot;
  const isHuman = player.is_human;
  const accent = isBot ? C.gold : isHuman ? C.blue : C.dimText;
  return (
    <div style={{
      background: player.folded ? "#0a140a" : isBot ? "#1a1500" : isHuman ? "#08101e" : "#0d1a2e",
      border: `1px solid ${isYourTurn ? C.blue : "#1a3a1a"}`,
      borderRadius: 10, padding: "10px 12px", minWidth: 160,
      opacity: player.folded ? 0.4 : 1, transition: "all 0.3s",
      boxShadow: isYourTurn ? `0 0 20px ${C.blue}66` : "none",
      position: "relative",
    }}>
      {isDealer && (
        <div style={{ position: "absolute", top: -8, right: -8, background: C.gold,
          color: "#000", borderRadius: "50%", width: 18, height: 18,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 9, fontWeight: 900 }}>D</div>
      )}
      {isYourTurn && (
        <div style={{ position: "absolute", top: -8, left: 8, background: C.blue,
          color: "#fff", borderRadius: 4, padding: "1px 7px", fontSize: 9, fontWeight: 700 }}>
          YOUR TURN
        </div>
      )}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <span style={{ color: accent, fontSize: 12, fontWeight: 700 }}>
          {isBot ? "🤖 " : isHuman ? "👤 " : ""}{player.name}
        </span>
        {player.folded && <span style={{ color: C.red, fontSize: 10 }}>FOLDED</span>}
        {player.all_in && <span style={{ color: C.gold, fontSize: 10 }}>ALL-IN</span>}
      </div>
      <div style={{ color: C.white, fontSize: 16, fontWeight: 700, fontFamily: "monospace", marginBottom: 4 }}>
        ${player.chips.toLocaleString()}
      </div>
      <ChipBar chips={player.chips} max={startChips} />
      <div style={{ display: "flex", gap: 4, marginTop: 8, flexWrap: "wrap" }}>
        {player.hole_cards?.map((c, i) => <Card key={i} card={c} small glow={isBot || isHuman} />)}
        {player.hole_cards_hidden && <><Card hidden small /><Card hidden small /></>}
      </div>
      {player.current_bet > 0 && (
        <div style={{ marginTop: 6, fontSize: 11, color: C.gold }}>Bet: ${player.current_bet}</div>
      )}
    </div>
  );
}

// ─── Human Action Panel ───────────────────────────────────────────────────────
function PlayerActionPanel({ turnInfo, onAction }) {
  const [raiseAmt, setRaiseAmt] = useState(turnInfo?.min_raise || 0);
  useEffect(() => { setRaiseAmt(turnInfo?.min_raise || 0); }, [turnInfo]);
  if (!turnInfo) return null;
  const { to_call, pot, chips, hand_cards, hand_name, min_raise, big_blind } = turnInfo;
  const canCheck = to_call === 0;
  const potOdds = to_call > 0 ? ((to_call / (pot + to_call)) * 100).toFixed(1) : null;

  const Btn = ({ label, color, onClick, disabled }) => (
    <button onClick={onClick} disabled={disabled} style={{
      background: disabled ? "#1a2a1a" : color, color: disabled ? C.dimText : "#000",
      border: "none", borderRadius: 8, padding: "12px 20px",
      fontSize: 14, fontWeight: 700, cursor: disabled ? "not-allowed" : "pointer",
      minWidth: 100, letterSpacing: 0.5,
    }}>
      {label}
    </button>
  );

  return (
    <div style={{
      position: "fixed", bottom: 0, left: 0, right: 0, zIndex: 100,
      background: "linear-gradient(to top, #060d1f f0, #0b1530ee)",
      borderTop: `2px solid ${C.blue}`, padding: "14px 24px",
      display: "flex", gap: 20, alignItems: "center", flexWrap: "wrap",
    }}>
      {/* Cards + hand name */}
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        {hand_cards?.map((c, i) => <Card key={i} card={c} glow />)}
        {hand_name && (
          <div style={{ marginLeft: 8 }}>
            <div style={{ color: C.dimText, fontSize: 10 }}>YOUR HAND</div>
            <div style={{ color: C.blue, fontSize: 13, fontWeight: 700 }}>{hand_name}</div>
          </div>
        )}
      </div>

      {/* Info row */}
      <div style={{ display: "flex", gap: 18 }}>
        {[["POT", `$${pot}`, C.gold], to_call > 0 && ["TO CALL", `$${to_call}`, C.red],
          potOdds && ["POT ODDS", `${potOdds}%`, C.purple],
          ["CHIPS", `$${chips}`, C.green]
        ].filter(Boolean).map(([k, v, col]) => (
          <div key={k}>
            <div style={{ color: C.dimText, fontSize: 9 }}>{k}</div>
            <div style={{ color: col, fontFamily: "monospace", fontWeight: 700, fontSize: 15 }}>{v}</div>
          </div>
        ))}
      </div>

      {/* Raise slider */}
      <div style={{ flex: 1, minWidth: 180 }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
          <span style={{ color: C.dimText, fontSize: 10 }}>RAISE TO</span>
          <span style={{ color: C.gold, fontFamily: "monospace", fontWeight: 700 }}>${raiseAmt}</span>
        </div>
        <input type="range" min={min_raise} max={chips} step={big_blind}
          value={raiseAmt} onChange={e => setRaiseAmt(Number(e.target.value))}
          style={{ width: "100%", accentColor: C.gold }} />
      </div>

      {/* Buttons */}
      <div style={{ display: "flex", gap: 10 }}>
        <Btn label="FOLD" color={C.red} onClick={() => onAction("fold", 0)} />
        {canCheck
          ? <Btn label="CHECK" color={C.dimText} onClick={() => onAction("check", 0)} />
          : <Btn label={`CALL $${to_call}`} color={C.blue} onClick={() => onAction("call", to_call)} disabled={to_call > chips} />
        }
        <Btn label={`RAISE $${raiseAmt}`} color={C.green}
          onClick={() => onAction("raise", raiseAmt)}
          disabled={raiseAmt < min_raise || raiseAmt > chips} />
      </div>
    </div>
  );
}

// ─── Bot Brain ────────────────────────────────────────────────────────────────
function BrainFeed({ logs, equity, potOdds, hasFlushDraw, hasStraightDraw, lastAction }) {
  const ref = useRef();
  useEffect(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight; }, [logs]);
  const aColor = a => ({ fold: C.red, call: C.blue, raise: C.green, bet: C.green, check: C.dimText }[a?.toLowerCase()] || C.white);
  return (
    <div style={{ background: C.navy, borderRadius: 10, padding: 14, border: `1px solid ${C.gold}33` }}>
      <div style={{ color: C.gold, fontSize: 11, fontWeight: 700, letterSpacing: 2, marginBottom: 10 }}>BOT BRAIN</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
        {[["EQUITY", equity, C.green], ["POT ODDS", potOdds, C.blue]].map(([label, val, col]) => (
          <div key={label} style={{ background: C.navyMid, borderRadius: 6, padding: 8 }}>
            <div style={{ color: C.dimText, fontSize: 9 }}>{label}</div>
            <div style={{ color: col, fontSize: 20, fontWeight: 700, fontFamily: "monospace" }}>
              {val ?? "—"}<span style={{ fontSize: 11 }}>%</span>
            </div>
            <div style={{ width: "100%", height: 3, background: "#0a1a0a", borderRadius: 2, marginTop: 4 }}>
              <div style={{ width: `${Math.min(val ?? 0, 100)}%`, height: "100%", background: col, borderRadius: 2, transition: "width 0.5s" }} />
            </div>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
        {hasFlushDraw && <span style={{ background: "#1a0a3a", color: C.purple, fontSize: 10, padding: "2px 8px", borderRadius: 4 }}>FLUSH DRAW</span>}
        {hasStraightDraw && <span style={{ background: "#1a1a0a", color: C.gold, fontSize: 10, padding: "2px 8px", borderRadius: 4 }}>STRAIGHT DRAW</span>}
      </div>
      {lastAction && (
        <div style={{ background: "#0a1a0a", borderRadius: 6, padding: "6px 10px", marginBottom: 8, border: `1px solid ${aColor(lastAction.action)}33` }}>
          <span style={{ color: C.dimText, fontSize: 10 }}>DECISION → </span>
          <span style={{ color: aColor(lastAction.action), fontSize: 13, fontWeight: 700, textTransform: "uppercase" }}>{lastAction.action}</span>
          {lastAction.amount > 0 && <span style={{ color: C.gold, fontSize: 11, marginLeft: 6 }}>${lastAction.amount}</span>}
        </div>
      )}
      <div ref={ref} style={{ overflowY: "auto", maxHeight: 180, fontFamily: "monospace", fontSize: 11 }}>
        {logs.map((log, i) => (
          <div key={i} style={{ color: C.dimText, padding: "2px 0", borderBottom: "1px solid #0a1a0a", lineHeight: 1.5 }}>
            <span style={{ color: C.gold, marginRight: 6 }}>›</span>{log}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Opponent Stats ───────────────────────────────────────────────────────────
function OpponentStats({ reads }) {
  const aColor = a => ({ TAG: C.green, LAG: C.red, FISH: C.blue, ROCK: C.dimText }[a] || C.gold);
  if (!reads?.length) return <div style={{ color: C.dimText, fontSize: 12, padding: 8 }}>Gathering reads...</div>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {reads.map(r => (
        <div key={r.name} style={{ background: C.navyMid, borderRadius: 8, padding: "8px 12px", border: "1px solid #1a2a3a" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <span style={{ color: C.white, fontSize: 12, fontWeight: 600 }}>{r.name}</span>
            <span style={{ color: aColor(r.archetype), fontSize: 10, background: "#0a1020", padding: "2px 8px", borderRadius: 4, fontWeight: 700 }}>{r.archetype}</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 4, fontSize: 10 }}>
            {[["VPIP", `${r.vpip}%`, C.green], ["PFR", `${r.pfr}%`, C.blue], ["AF", r.aggression_factor, C.red],
              ["Avg Bet", `${r.avg_bet_pct_bb}%BB`, C.gold], ["Fold/3B", `${r.fold_to_3bet}%`, C.purple], ["Hands", r.hands_seen, C.dimText]
            ].map(([k, v, col]) => (
              <div key={k}>
                <div style={{ color: C.dimText, fontSize: 9 }}>{k}</div>
                <div style={{ color: col, fontFamily: "monospace", fontWeight: 700 }}>{v}</div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Stats Bar ────────────────────────────────────────────────────────────────
function StatsBar({ stats }) {
  const n = stats.hands_played;
  const bb100 = n > 0 ? ((stats.bb_won / n) * 100).toFixed(1) : "—";
  const sdWin = stats.showdowns > 0 ? ((stats.showdown_wins / stats.showdowns) * 100).toFixed(0) + "%" : "—";
  const vpip = n > 0 ? ((stats.vpip / n) * 100).toFixed(0) + "%" : "—";
  const winPct = n > 0 ? ((stats.hands_won / n) * 100).toFixed(0) + "%" : "—";
  return (
    <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
      {[["BB/100", bb100, parseFloat(bb100) >= 0 ? C.green : C.red],
        ["Hands", n, C.white], ["Win%", winPct, C.blue],
        ["SD Win", sdWin, C.purple], ["VPIP", vpip, C.gold]
      ].map(([k, v, col]) => (
        <div key={k} style={{ textAlign: "center" }}>
          <div style={{ color: C.dimText, fontSize: 9, letterSpacing: 1 }}>{k}</div>
          <div style={{ color: col, fontSize: 16, fontWeight: 700, fontFamily: "monospace" }}>{v}</div>
        </div>
      ))}
    </div>
  );
}

// ─── Action Log ───────────────────────────────────────────────────────────────
function ActionLog({ log }) {
  const ref = useRef();
  useEffect(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight; }, [log]);
  const style = t => ({ player_action: C.white, street: C.gold, showdown: C.green, hand_start: C.dimText, blinds_posted: C.dimText }[t] || C.dimText);
  return (
    <div ref={ref} style={{ overflowY: "auto", maxHeight: 130, fontFamily: "monospace", fontSize: 11 }}>
      {log.map((e, i) => (
        <div key={i} style={{ padding: "2px 0", borderBottom: "1px solid #0a1a0a", color: style(e.type) }}>{e.msg}</div>
      ))}
    </div>
  );
}

// ─── Setup Screen ─────────────────────────────────────────────────────────────
function SetupScreen({ onStart }) {
  const [players, setPlayers] = useState(5);
  const [bb, setBb] = useState(20);
  const [chips, setChips] = useState(1000);
  const [joinAsPlayer, setJoinAsPlayer] = useState(false);
  const [humanName, setHumanName] = useState("");

  return (
    <div style={{ minHeight: "100vh", background: C.navy, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ background: C.navyMid, borderRadius: 16, padding: 40, border: `1px solid ${C.gold}44`, maxWidth: 440, width: "100%" }}>
        <div style={{ textAlign: "center", marginBottom: 28 }}>
          <div style={{ fontSize: 40 }}>🃏</div>
          <h1 style={{ color: C.gold, fontFamily: "Georgia, serif", fontSize: 26, margin: "8px 0 4px" }}>Adaptive Poker Bot</h1>
          <p style={{ color: C.dimText, fontSize: 13, margin: 0 }}>AI that models opponents and adapts in real time</p>
        </div>

        {[["Players at table", players, setPlayers, 3, 9, 1],
          ["Big blind ($)", bb, setBb, 10, 200, 10],
          ["Starting chips ($)", chips, setChips, 200, 5000, 100]
        ].map(([label, val, setter, min, max, step]) => (
          <div key={label} style={{ marginBottom: 18 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
              <span style={{ color: C.white, fontSize: 13 }}>{label}</span>
              <span style={{ color: C.gold, fontFamily: "monospace", fontWeight: 700 }}>{val}</span>
            </div>
            <input type="range" min={min} max={max} step={step} value={val}
              onChange={e => setter(Number(e.target.value))}
              style={{ width: "100%", accentColor: C.gold }} />
          </div>
        ))}

        {/* Join toggle */}
        <div style={{ background: "#0a1020", borderRadius: 10, padding: 14, marginBottom: 20, border: "1px solid #1a2a4a" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <div style={{ color: C.white, fontSize: 13, fontWeight: 600 }}>Join as a player</div>
              <div style={{ color: C.dimText, fontSize: 11, marginTop: 2 }}>Play hands yourself alongside the bot</div>
            </div>
            <div onClick={() => setJoinAsPlayer(j => !j)} style={{
              width: 44, height: 24, borderRadius: 12, cursor: "pointer",
              background: joinAsPlayer ? C.blue : "#1a2a3a", position: "relative", transition: "background 0.2s",
            }}>
              <div style={{
                position: "absolute", top: 3, width: 18, height: 18, borderRadius: "50%",
                background: C.white, transition: "left 0.2s", left: joinAsPlayer ? 22 : 3,
              }} />
            </div>
          </div>
          {joinAsPlayer && (
            <input placeholder="Your name" value={humanName} onChange={e => setHumanName(e.target.value)}
              style={{
                marginTop: 12, width: "100%", background: "#060d1f", color: C.white,
                border: `1px solid ${C.blue}55`, borderRadius: 6, padding: "8px 12px",
                fontSize: 13, outline: "none", boxSizing: "border-box",
              }} />
          )}
        </div>

        <button onClick={() => onStart({ players, bb, chips, humanName: joinAsPlayer ? (humanName || "You") : null })}
          style={{
            width: "100%", padding: "14px 0", background: C.gold, color: "#000",
            border: "none", borderRadius: 8, fontSize: 15, fontWeight: 700,
            cursor: "pointer", letterSpacing: 1,
          }}>
          DEAL ME IN
        </button>
      </div>
    </div>
  );
}

// ─── Main App ─────────────────────────────────────────────────────────────────
export default function App() {
  const ws = useRef(null);
  const [screen, setScreen] = useState("setup");
  const [connected, setConnected] = useState(false);
  const [state, setState] = useState(null);
  const [brainLogs, setBrainLogs] = useState([]);
  const [equity, setEquity] = useState(null);
  const [potOdds, setPotOdds] = useState(null);
  const [flushDraw, setFlushDraw] = useState(false);
  const [straightDraw, setStraightDraw] = useState(false);
  const [lastAction, setLastAction] = useState(null);
  const [actionLog, setActionLog] = useState([]);
  const [playing, setPlaying] = useState(false);
  const [startChips, setStartChips] = useState(1000);
  const [street, setStreet] = useState(null);
  const [humanTurn, setHumanTurn] = useState(null);

  const addLog = (type, msg) => setActionLog(l => [...l.slice(-80), { type, msg }]);

  const send = useCallback((data) => {
    if (ws.current?.readyState === WebSocket.OPEN)
      ws.current.send(JSON.stringify(data));
  }, []);

  const handleHumanAction = useCallback((action, amount) => {
    setHumanTurn(null);
    send({ cmd: "human_action", action, amount });
    const verb = { fold: "folds", call: "calls", raise: "raises to", check: "checks" }[action] || action;
    addLog("player_action", `👤 You ${verb}${amount > 0 ? ` $${amount}` : ""}`);
  }, [send]);

  const connect = useCallback((config) => {
    const socket = new WebSocket("wss://poker-bot-production-284c.up.railway.app/ws");
    ws.current = socket;

    socket.onopen = () => {
      setConnected(true);
      socket.send(JSON.stringify({
        cmd: "setup",
        num_players: config.players,
        big_blind: config.bb,
        starting_chips: config.chips,
        human_name: config.humanName || null,
      }));
    };

    socket.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.state) setState(msg.state);

      switch (msg.type) {
        case "ready":
          setScreen("game"); setPlaying(false);
          addLog("hand_start", "✓ Table ready — click Deal to start");
          break;
        case "hand_start":
          setBrainLogs([]); setLastAction(null); setEquity(null);
          setPotOdds(null); setFlushDraw(false); setStraightDraw(false);
          setStreet("preflop"); setHumanTurn(null);
          addLog("hand_start", `━━ Hand #${msg.hand_num} ━━`);
          break;
        case "blinds_posted":
          addLog("blinds_posted", `${msg.sb} posts SB $${msg.sb_amount}  |  ${msg.bb} posts BB $${msg.bb_amount}`);
          break;
        case "bot_thinking":
          setBrainLogs(l => [...l.slice(-30), ...msg.logs]);
          setEquity(msg.equity); setPotOdds(msg.pot_odds);
          setFlushDraw(msg.has_flush_draw); setStraightDraw(msg.has_straight_draw);
          setLastAction({ action: msg.action, amount: msg.amount });
          break;
        case "human_turn":
          setHumanTurn(msg);
          addLog("player_action", `👤 Your turn — ${msg.to_call > 0 ? `call $${msg.to_call} or raise` : "check or bet"}`);
          break;
        case "player_action":
          if (!msg.is_human) {
            const verb = { fold: "folds", call: "calls", raise: "raises to", bet: "bets", check: "checks" }[msg.action] || msg.action;
            const amt = msg.amount > 0 ? ` $${msg.amount}` : "";
            addLog("player_action", `${msg.is_bot ? "🤖" : "·"} ${msg.player} ${verb}${amt}  (pot $${msg.pot})`);
          }
          break;
        case "street":
          setStreet(msg.street); setHumanTurn(null);
          addLog("street", `── ${msg.street.toUpperCase()}  ${msg.new_cards?.map(c => c.display).join(" ") || ""}`);
          break;
        case "showdown":
          setHumanTurn(null);
          addLog("showdown", `🏆 ${msg.winner} wins $${msg.pot}  (bot: ${msg.chip_delta >= 0 ? "+" : ""}$${msg.chip_delta})`);
          msg.players?.forEach(p => addLog("showdown", `  ${p.name}: ${p.cards?.map(c => c.display).join(" ")} → ${p.hand_name}`));
          break;
        case "hand_complete":
          setPlaying(false); setHumanTurn(null);
          break;
        case "error":
          addLog("hand_start", `⚠ ${msg.message}`);
          setPlaying(false); setHumanTurn(null);
          break;
      }
    };

    socket.onclose = () => { setConnected(false); setHumanTurn(null); };
    socket.onerror = () => { setConnected(false); setHumanTurn(null); };
  }, []);

  if (screen === "setup") return <SetupScreen onStart={config => { setStartChips(config.chips); connect(config); }} />;

  const community = state?.community_cards || [];

  return (
    <div style={{ minHeight: "100vh", background: C.navy, color: C.white,
      fontFamily: "system-ui, sans-serif", padding: 16,
      paddingBottom: humanTurn ? 160 : 16 }}>

      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 22 }}>🃏</span>
          <div>
            <div style={{ color: C.gold, fontSize: 16, fontWeight: 700, fontFamily: "Georgia, serif" }}>Adaptive Poker Bot</div>
            <div style={{ color: C.dimText, fontSize: 11 }}>
              {connected ? "● Connected" : "○ Disconnected"}
              {state && `  ·  Hand #${state.hand_num}  ·  ${street || "—"}`}
              {humanTurn && <span style={{ color: C.blue, marginLeft: 8, fontWeight: 700 }}>● YOUR TURN</span>}
            </div>
          </div>
        </div>
        {state && <StatsBar stats={state.stats} />}
        <button onClick={() => { if (!playing && connected && !humanTurn) { setPlaying(true); send({ cmd: "deal" }); } }}
          disabled={playing || !connected || !!humanTurn}
          style={{
            background: (playing || humanTurn) ? C.bark : C.gold,
            color: (playing || humanTurn) ? C.dimText : "#000",
            border: "none", borderRadius: 8, padding: "10px 24px",
            fontSize: 14, fontWeight: 700,
            cursor: (playing || humanTurn) ? "not-allowed" : "pointer",
            letterSpacing: 1,
          }}>
          {playing ? (humanTurn ? "YOUR TURN ↓" : "PLAYING...") : "DEAL"}
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: 16 }}>
        <div>
          {/* Felt table */}
          <div style={{
            background: `radial-gradient(ellipse at center, ${C.feltMid} 0%, ${C.felt} 60%, ${C.feltRim} 100%)`,
            borderRadius: 120, border: "8px solid #05200e",
            boxShadow: "0 0 40px #00000088, inset 0 0 60px #00000033",
            padding: "32px 48px", marginBottom: 16, minHeight: 260,
          }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
              <div style={{ color: C.gold, fontSize: 10, letterSpacing: 2, marginBottom: 10, opacity: 0.7 }}>
                {street?.toUpperCase() || "PRE-FLOP"}
              </div>
              <div style={{ display: "flex", gap: 8, minHeight: 72, alignItems: "center" }}>
                {community.length > 0
                  ? community.map((c, i) => <Card key={i} card={c} glow />)
                  : <div style={{ color: "#2a5a3a", fontSize: 13 }}>Waiting for flop...</div>}
              </div>
              {state?.pot > 0 && (
                <div style={{ marginTop: 12, background: "#00000033", color: C.gold,
                  borderRadius: 20, padding: "4px 16px", fontSize: 14, fontWeight: 700, fontFamily: "monospace" }}>
                  Pot: ${state.pot.toLocaleString()}
                </div>
              )}
            </div>
          </div>

          {/* Player seats */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, justifyContent: "center" }}>
            {state?.players?.map((p, i) => (
              <PlayerSeat key={p.name} player={p}
                isDealer={i === state.dealer_idx}
                startChips={startChips}
                isYourTurn={!!humanTurn && p.is_human} />
            ))}
          </div>

          {/* Action log */}
          <div style={{ background: C.navyMid, borderRadius: 10, padding: 12, marginTop: 14, border: "1px solid #1a2a3a" }}>
            <div style={{ color: C.dimText, fontSize: 10, letterSpacing: 2, marginBottom: 8 }}>ACTION LOG</div>
            <ActionLog log={actionLog} />
          </div>
        </div>

        {/* Sidebar */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <BrainFeed logs={brainLogs} equity={equity} potOdds={potOdds}
            hasFlushDraw={flushDraw} hasStraightDraw={straightDraw} lastAction={lastAction} />
          <div style={{ background: C.navyMid, borderRadius: 10, padding: 14, border: "1px solid #1a2a3a" }}>
            <div style={{ color: C.gold, fontSize: 11, fontWeight: 700, letterSpacing: 2, marginBottom: 10 }}>OPPONENT READS</div>
            <OpponentStats reads={state?.opponent_reads} />
          </div>
        </div>
      </div>

      <div style={{ textAlign: "center", color: C.dimText, fontSize: 10, marginTop: 16 }}>
        FastAPI + WebSocket · Monte Carlo equity · Opponent modeling: VPIP / PFR / AF
      </div>

      {humanTurn && <PlayerActionPanel turnInfo={humanTurn} onAction={handleHumanAction} />}
    </div>
  );
}
