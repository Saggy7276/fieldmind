import { useState, useEffect, useRef, useCallback } from "react";

const API_BASE = "http://localhost:8000";
const WS_URL   = "ws://localhost:8000/ws/ask";

// ── Global styles ────────────────────────────────────────────────────────────
const STYLES = `
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@300;400;500&family=Barlow:wght@300;400;600;700;900&display=swap');

*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}

:root{
  --bg:      #07080b;
  --s1:      #0d0f14;
  --s2:      #13161d;
  --border:  #1c2030;
  --green:   #1aff8c;
  --blue:    #38b6ff;
  --amber:   #ffb830;
  --red:     #ff4455;
  --text:    #dde2f0;
  --muted:   #454d6a;
  --mono:    'DM Mono', monospace;
  --sans:    'Barlow', sans-serif;
}

html,body,#root{height:100%;background:var(--bg);}
body{font-family:var(--sans);color:var(--text);overflow:hidden;}

/* ── layout ── */
.shell{
  display:grid;
  grid-template-rows:52px 1fr;
  grid-template-columns:220px 1fr 260px;
  height:100vh;
}

/* ── topbar ── */
.topbar{
  grid-column:1/-1;
  display:flex;align-items:center;gap:14px;
  padding:0 22px;
  background:var(--s1);
  border-bottom:1px solid var(--border);
}
.logo{font-size:17px;font-weight:900;letter-spacing:-.3px;}
.logo em{color:var(--green);font-style:normal;}
.pill{
  display:flex;align-items:center;gap:5px;
  font-family:var(--mono);font-size:10px;
  padding:3px 9px;border-radius:99px;
  border:1px solid var(--border);color:var(--muted);
}
.dot{width:6px;height:6px;border-radius:50%;background:var(--muted);}
.dot.on{background:var(--green);box-shadow:0 0 6px var(--green);animation:glow 2s infinite;}
.dot.err{background:var(--red);}
@keyframes glow{0%,100%{opacity:1}50%{opacity:.4}}
.topbar-right{margin-left:auto;display:flex;align-items:center;gap:16px;}
.mono-sm{font-family:var(--mono);font-size:10px;color:var(--muted);}

/* ── left panel ── */
.left{
  background:var(--s1);border-right:1px solid var(--border);
  padding:18px 14px;display:flex;flex-direction:column;gap:18px;
  overflow-y:auto;
}
.panel-title{
  font-family:var(--mono);font-size:9px;letter-spacing:2.5px;
  text-transform:uppercase;color:var(--muted);margin-bottom:6px;
}
.kpi{
  background:var(--s2);border:1px solid var(--border);
  border-radius:8px;padding:11px 13px;
}
.kpi-val{font-size:26px;font-weight:900;line-height:1;}
.kpi-val.g{color:var(--green);}
.kpi-val.b{color:var(--blue);}
.kpi-val.r{color:var(--red);}
.kpi-lbl{font-family:var(--mono);font-size:10px;color:var(--muted);margin-top:3px;}
.bar-wrap{height:3px;border-radius:2px;background:var(--border);margin-top:8px;overflow:hidden;}
.bar-fill{
  height:100%;border-radius:2px;
  background:linear-gradient(90deg,var(--green),var(--blue));
  transition:width .6s cubic-bezier(.4,0,.2,1);
}
.info-block{
  background:var(--s2);border:1px solid var(--border);
  border-radius:8px;padding:11px 13px;
  font-family:var(--mono);font-size:10px;color:var(--muted);line-height:2;
}
.info-block .on{color:var(--green);}
.info-block .bl{color:var(--blue);}

/* ── main ── */
.main{display:flex;flex-direction:column;overflow:hidden;}

/* waveform canvas */
.wave-bar{
  height:64px;background:var(--s1);border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:center;position:relative;
  overflow:hidden;
}
.wave-label{
  position:absolute;left:14px;
  font-family:var(--mono);font-size:10px;
  color:var(--muted);letter-spacing:1px;
}
.wave-state{
  position:absolute;right:14px;
  font-family:var(--mono);font-size:10px;letter-spacing:1.5px;
}
canvas.wave{width:100%;height:100%;}

/* conversation */
.conv{
  flex:1;overflow-y:auto;padding:20px 22px;
  display:flex;flex-direction:column;gap:14px;
  scroll-behavior:smooth;
}
.conv::-webkit-scrollbar{width:3px;}
.conv::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px;}

.msg{display:flex;flex-direction:column;gap:3px;max-width:72%;animation:fadeup .2s ease;}
@keyframes fadeup{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.msg.op{align-self:flex-end;align-items:flex-end;}
.msg.ai{align-self:flex-start;}
.msg-meta{font-family:var(--mono);font-size:9px;color:var(--muted);}
.bubble{padding:10px 14px;border-radius:10px;font-size:13.5px;line-height:1.65;}
.msg.op .bubble{background:#38b6ff14;border:1px solid #38b6ff35;color:var(--text);}
.msg.ai .bubble{background:var(--s2);border:1px solid var(--border);color:var(--text);}
.msg.esc .bubble{border-color:var(--red)!important;background:#ff445510!important;}
.esc-tag{font-family:var(--mono);font-size:9px;color:var(--red);letter-spacing:1px;}
.cursor{
  display:inline-block;width:7px;height:13px;
  background:var(--green);border-radius:1px;margin-left:2px;
  animation:blink .75s infinite;vertical-align:middle;
}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}
.empty-state{
  flex:1;display:flex;flex-direction:column;
  align-items:center;justify-content:center;
  color:var(--muted);font-family:var(--mono);font-size:12px;gap:10px;
  padding-top:40px;
}
.empty-icon{font-size:36px;filter:grayscale(1);opacity:.4;}

/* input bar */
.ibar{
  padding:13px 18px;border-top:1px solid var(--border);
  background:var(--s1);display:flex;gap:9px;align-items:center;
}
.ifield{
  flex:1;background:var(--bg);
  border:1px solid var(--border);border-radius:8px;
  padding:9px 13px;font-size:13px;
  font-family:var(--sans);color:var(--text);outline:none;
  transition:border-color .15s;
}
.ifield:focus{border-color:var(--blue);}
.ifield::placeholder{color:var(--muted);}
.ifield:disabled{opacity:.4;}
.btn{
  border:none;border-radius:8px;
  font-family:var(--sans);font-weight:700;font-size:12px;
  cursor:pointer;transition:all .14s;padding:9px 16px;
}
.btn:disabled{opacity:.35;cursor:not-allowed;}
.btn-send{background:var(--green);color:#000;}
.btn-send:hover:not(:disabled){background:#33ffaa;transform:translateY(-1px);}
.btn-mic{
  background:var(--s2);border:1px solid var(--border);
  color:var(--muted);padding:9px 13px;font-size:16px;
}
.btn-mic:hover:not(:disabled){border-color:var(--green);color:var(--green);}
.btn-mic.active{
  background:#1aff8c15;border-color:var(--green);
  color:var(--green);animation:glow 1s infinite;
}
.btn-mic.speaking{
  background:#38b6ff15;border-color:var(--blue);
  color:var(--blue);
}

/* ── right log ── */
.right{
  background:var(--s1);border-left:1px solid var(--border);
  display:flex;flex-direction:column;overflow:hidden;
}
.log-head{
  padding:13px 14px;border-bottom:1px solid var(--border);
  display:flex;justify-content:space-between;align-items:center;
}
.log-entries{
  flex:1;overflow-y:auto;padding:8px 10px;
  display:flex;flex-direction:column;gap:3px;
  font-family:var(--mono);font-size:10px;
}
.log-entries::-webkit-scrollbar{width:2px;}
.log-entries::-webkit-scrollbar-thumb{background:var(--border);}
.le{
  display:flex;gap:7px;padding:4px 7px;
  border-radius:4px;line-height:1.5;animation:fadeup .15s ease;
}
.le:hover{background:var(--s2);}
.le-t{color:var(--muted);flex-shrink:0;}
.le-m{color:var(--text);}
.le.g .le-m{color:var(--green);}
.le.b .le-m{color:var(--blue);}
.le.r .le-m{color:var(--red);}
.le.a .le-m{color:var(--amber);}
.le.d .le-m{color:var(--muted);}
.clr-btn{
  background:none;border:none;font-family:var(--mono);
  font-size:9px;letter-spacing:1px;text-transform:uppercase;
  color:var(--muted);cursor:pointer;
}
.clr-btn:hover{color:var(--red);}
`;

// ── helpers ──────────────────────────────────────────────────────────────────
let _uid = 0;
const uid  = () => ++_uid;
const hms  = () => new Date().toLocaleTimeString("en-GB",{hour12:false});
const pad2 = n => String(n).padStart(2,"0");
const fmt  = s => `${pad2(Math.floor(s/3600))}:${pad2(Math.floor(s%3600/60))}:${pad2(s%60)}`;

// Web Speech synthesis — speak text in browser (zero latency, no round-trip)
function browserSpeak(text, rate = 0.92) {
  if (!window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.rate = rate;
  u.pitch = 1.0;
  u.volume = 1.0;
  const voices = window.speechSynthesis.getVoices();
  const voice = voices.find(v => v.lang === "en-US" && v.localService);
  if (voice) u.voice = voice;
  window.speechSynthesis.speak(u);
}
function cancelSpeak() {
  window.speechSynthesis?.cancel();
}

// ── main component ────────────────────────────────────────────────────────────
export default function FieldMind() {
  const [health,    setHealth]    = useState("checking");
  const [uptime,    setUptime]    = useState(0);
  const [msgs,      setMsgs]      = useState([]);
  const [logs,      setLogs]      = useState([]);
  const [input,     setInput]     = useState("");
  const [busy,      setBusy]      = useState(false);
  const [micState,  setMicState]  = useState("idle");  // idle | listening | speaking
  const [stats,     setStats]     = useState({q:0, esc:0, lats:[], avg:"0.00"});
  const [vadActive, setVadActive] = useState(false);

  const wsRef        = useRef(null);
  const convRef      = useRef(null);
  const logRef       = useRef(null);
  const canvasRef    = useRef(null);
  const animRef      = useRef(null);
  const analyserRef  = useRef(null);
  const mediaRef     = useRef(null);
  const recognRef    = useRef(null);
  const t0Ref        = useRef(null);

  // ── log ──
  const log = useCallback((m, t="d") => {
    setLogs(p => [...p.slice(-249), {id:uid(), time:hms(), m, t}]);
  }, []);

  // ── health ──
  useEffect(() => {
    const check = async () => {
      try {
        await fetch(`${API_BASE}/health`);
        setHealth("online"); log("Backend online","g");
      } catch { setHealth("error"); log("Backend unreachable","r"); }
    };
    check();
    const id = setInterval(check, 15000);
    return () => clearInterval(id);
  }, [log]);

  // ── uptime ──
  useEffect(() => {
    const id = setInterval(() => setUptime(u => u+1), 1000);
    return () => clearInterval(id);
  }, []);

  // ── auto-scroll ──
  useEffect(() => { convRef.current?.scrollTo({top:9999,behavior:"smooth"}); }, [msgs]);
  useEffect(() => { logRef.current?.scrollTo({top:9999,behavior:"smooth"}); }, [logs]);

  // ── waveform visualizer ──
  const startVisualizer = useCallback(async () => {
    if (analyserRef.current) return;
    try {
      const stream   = await navigator.mediaDevices.getUserMedia({audio:true});
      mediaRef.current = stream;
      const ctx      = new AudioContext();
      const src      = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 128;
      src.connect(analyser);
      analyserRef.current = analyser;

      const canvas = canvasRef.current;
      const draw   = () => {
        animRef.current = requestAnimationFrame(draw);
        if (!canvas) return;
        const dctx = canvas.getContext("2d");
        const W = canvas.width, H = canvas.height;
        const buf = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteFrequencyData(buf);
        dctx.clearRect(0,0,W,H);

        const barW = W / buf.length;
        buf.forEach((v, i) => {
          const h = (v / 255) * H * .85;
          const alpha = .4 + (v/255)*.6;
          const x = i * barW;
          const grd = dctx.createLinearGradient(0, H-h, 0, H);
          grd.addColorStop(0, `rgba(26,255,140,${alpha})`);
          grd.addColorStop(1, `rgba(56,182,255,${alpha*.5})`);
          dctx.fillStyle = grd;
          dctx.fillRect(x, H-h, barW-1, h);
        });
      };
      draw();
    } catch(e) { log("Mic access denied","r"); }
  }, [log]);

  const stopVisualizer = useCallback(() => {
    cancelAnimationFrame(animRef.current);
    analyserRef.current = null;
    mediaRef.current?.getTracks().forEach(t => t.stop());
    mediaRef.current = null;
    const canvas = canvasRef.current;
    if (canvas) canvas.getContext("2d").clearRect(0,0,canvas.width,canvas.height);
  }, []);

  // ── WebSocket send ──
  const sendQuestion = useCallback((question) => {
    if (!question.trim() || busy) return;
    cancelSpeak();

    const qid = uid();
    setMsgs(p => [...p, {id:qid, role:"op", text:question, time:hms()}]);
    log(`Query: "${question.slice(0,45)}${question.length>45?"…":""}"`, "b");

    const aid = uid();
    setMsgs(p => [...p, {id:aid, role:"ai", text:"", time:hms(), streaming:true}]);

    setBusy(true);
    setMicState("idle");
    t0Ref.current = Date.now();

    const connect = () => {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify({question}));
        log("WS stream open","d");
      };

      ws.onmessage = (e) => {
        const data = JSON.parse(e.data);

        if (data.type === "token") {
          setMsgs(p => p.map(m => m.id===aid ? {...m, text:m.text+data.content} : m));
        }
        else if (data.type === "speak") {
          setMicState("speaking");
          const u = new SpeechSynthesisUtterance(data.sentence);
          u.rate = 0.92;
          u.pitch = 1.0;
          u.volume = 1.0;
          const voices = window.speechSynthesis.getVoices();
          const voice = voices.find(v => v.lang === "en-US" && v.localService);
          if (voice) u.voice = voice;
          u.onend = () => setMicState("idle");
          window.speechSynthesis.speak(u);
          log(`TTS: "${data.sentence.slice(0,40)}…"`, "d");
        }
        else if (data.type === "done") {
          const lat = ((Date.now()-t0Ref.current)/1000).toFixed(2);
          setMsgs(p => p.map(m => m.id===aid
            ? {...m, streaming:false, escalate:data.escalate} : m));
          setStats(p => {
            const nl = [...p.lats, parseFloat(lat)].slice(-20);
            const avg = (nl.reduce((a,b)=>a+b,0)/nl.length).toFixed(2);
            return {q:p.q+1, esc:p.esc+(data.escalate?1:0), lats:nl, avg};
          });
          if (data.escalate) log("⚠ ESCALATE — specialist required","r");
          log(`Done in ${lat}s`, "g");
          setBusy(false);
          setMicState("idle");
        }
      };

      ws.onerror = () => { log("WS error","r"); setBusy(false); };
    };

    connect();
  }, [busy, log]);

  // ── Web Speech API — voice input ──
  const startListening = useCallback(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { log("SpeechRecognition not supported in this browser","r"); return; }
    if (busy) return;

    cancelSpeak();
    startVisualizer();

    const rec = new SR();
    rec.lang           = "en-US";
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    recognRef.current  = rec;

    setMicState("listening");
    log("Mic active — listening…","b");

    let final = "";

    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) final += t;
        else interim = t;
      }
      setInput(final || interim);
    };

    rec.onend = () => {
      stopVisualizer();
      setMicState("idle");
      const q = final.trim();
      if (q) { setInput(""); sendQuestion(q); }
      else   { log("No speech detected","a"); }
    };

    rec.onerror = (e) => {
      stopVisualizer();
      setMicState("idle");
      log(`STT error: ${e.error}`,"r");
    };

    rec.start();
  }, [busy, startVisualizer, stopVisualizer, sendQuestion, log]);

  const stopListening = useCallback(() => {
    recognRef.current?.stop();
  }, []);

  const handleKey = (e) => {
    if (e.key==="Enter"&&!e.shiftKey) { e.preventDefault(); sendQuestion(input); setInput(""); }
  };

  const micLabel = {idle:"🎤", listening:"⏹", speaking:"🔊"}[micState];
  const micClass = {idle:"btn-mic", listening:"btn-mic active", speaking:"btn-mic speaking"}[micState];
  const waveColor = micState==="listening"
    ? "var(--green)" : micState==="speaking" ? "var(--blue)" : "var(--muted)";
  const latPct = Math.min((parseFloat(stats.avg)/10)*100,100);

  return (
    <>
      <style>{STYLES}</style>
      <div className="shell">

        {/* topbar */}
        <header className="topbar">
          <div className="logo">Field<em>Mind</em></div>
          <div className="pill">
            <div className={`dot ${health==="online"?"on":health==="error"?"err":""}`}/>
            {health==="online"?"ONLINE":health==="error"?"OFFLINE":"INIT"}
          </div>
          <div className="pill" style={{color:"var(--blue)",borderColor:"#38b6ff30"}}>
            ⚡ fieldmind · mistral-7b-lora
          </div>
          <div className="topbar-right">
            <span className="mono-sm">⏱ {fmt(uptime)}</span>
          </div>
        </header>

        {/* left */}
        <aside className="left">
          <div>
            <div className="panel-title">Session</div>
            <div style={{display:"flex",flexDirection:"column",gap:8}}>
              <div className="kpi">
                <div className="kpi-val g">{stats.q}</div>
                <div className="kpi-lbl">Queries</div>
              </div>
              <div className="kpi">
                <div className="kpi-val r">{stats.esc}</div>
                <div className="kpi-lbl">Escalations</div>
              </div>
              <div className="kpi">
                <div className="kpi-val b">{stats.avg}s</div>
                <div className="kpi-lbl">Avg latency</div>
                <div className="bar-wrap"><div className="bar-fill" style={{width:`${latPct}%`}}/></div>
              </div>
            </div>
          </div>

          <div>
            <div className="panel-title">Stack</div>
            <div className="info-block">
              <span className="on">●</span> Ollama · fieldmind<br/>
              <span className="on">●</span> ChromaDB · about<br/>
              <span className="on">●</span> MiniLM-L6 RAG<br/>
              <span className="bl">●</span> Web Speech STT<br/>
              <span className="bl">●</span> SpeechSynthesis TTS<br/>
            </div>
          </div>

          <div>
            <div className="panel-title">Optimizations</div>
            <div className="info-block">
              VAD endpoint<br/>
              beam_size=1<br/>
              threaded TTS<br/>
              sentence streaming<br/>
              browser-native voice
            </div>
          </div>
        </aside>

        {/* main */}
        <main className="main">
          {/* waveform */}
          <div className="wave-bar" onClick={() => { cancelSpeak(); setMicState("idle"); }} style={{cursor: micState==="speaking"?"pointer":"default"}}>
            <span className="wave-label" style={{color:waveColor}}>
              {micState==="listening"?"● RECORDING":micState==="speaking"?"▶ SPEAKING":"○ STANDBY"}
            </span>
            <canvas
              ref={canvasRef}
              className="wave"
              width={800} height={64}
              style={{opacity: micState==="idle" ? 0.3 : 1, transition:"opacity .3s"}}
            />
          </div>

          {/* conversation */}
          <div className="conv" ref={convRef}>
            {msgs.length===0 && (
              <div className="empty-state">
                <div className="empty-icon">⚡</div>
                <div>FieldMind standing by</div>
                <div style={{fontSize:10}}>press mic or type a question</div>
              </div>
            )}
            {msgs.map(m => (
              <div key={m.id} className={`msg ${m.role} ${m.escalate?"esc":""}`}>
                <div className="msg-meta">
                  {m.role==="op"?"OPERATOR":"FIELDMIND"} · {m.time}
                  {m.escalate && <span className="esc-tag" style={{marginLeft:8}}>⚠ ESCALATE</span>}
                </div>
                <div className="bubble">
                  {m.text}
                  {m.streaming && <span className="cursor"/>}
                </div>
              </div>
            ))}
          </div>

          {/* input bar */}
          <div className="ibar">
            <button
              className={`btn ${micClass}`}
              onClick={micState==="listening" ? stopListening : startListening}
              disabled={busy && micState!=="listening"}
              title={micState==="listening"?"Stop recording":"Start voice input"}
            >
              {micLabel}
            </button>
            <input
              className="ifield"
              placeholder={busy ? "FieldMind responding…" : "Ask a field operations question…"}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKey}
              disabled={busy}
            />
            <button
              className="btn btn-send"
              onClick={() => { sendQuestion(input); setInput(""); }}
              disabled={busy || !input.trim()}
            >
              Send
            </button>
            {(busy || micState === "speaking") && (
              <button
                className="btn"
                style={{
                  background: "var(--red)",
                  color: "#fff",
                  fontWeight: 900,
                  fontSize: 13,
                  padding: "9px 18px",
                  letterSpacing: 1,
                }}
                onClick={() => {
                  if (wsRef.current) {
                    wsRef.current.onmessage = null;
                    wsRef.current.close();
                    wsRef.current = null;
                  }
                  cancelSpeak();
                  setMicState("idle");
                  setBusy(false);
                  setMsgs(p => p.map((m, i) =>
                    i === p.length - 1 && m.role === "ai"
                      ? {...m, streaming: false, stopped: true}
                      : m
                  ));
                  log("Response stopped by user", "a");
                }}
              >
                ⏹ STOP
              </button>
            )}
          </div>
        </main>

        {/* right log */}
        <aside className="right">
          <div className="log-head">
            <span className="panel-title" style={{marginBottom:0}}>System Log</span>
            <button className="clr-btn" onClick={()=>setLogs([])}>clear</button>
          </div>
          <div className="log-entries" ref={logRef}>
            {logs.map(e => (
              <div key={e.id} className={`le ${e.t}`}>
                <span className="le-t">{e.time}</span>
                <span className="le-m">{e.m}</span>
              </div>
            ))}
          </div>
        </aside>

      </div>
    </>
  );
}