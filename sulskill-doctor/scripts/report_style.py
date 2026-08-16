#!/usr/bin/env python3
"""Shared look for the HTML reports this skill generates.

One stylesheet, imported by every report, so they stay a set instead of
drifting into near-misses of each other. Each report supplies its own body and
its own filter logic; everything above that - tokens, the sticky command bar,
the plumbob, search, chips, cards, rows - comes from here.

The palette is The Sims 4's own: light and blue-white rather than the dark-neon
treatment a "game tool" defaults to, because that is what the game's UI
actually looks like. Dark mode is a full second palette, not an inversion, and
covers all three viewer states - explicit dark, explicit light, and the
unstamped default where only prefers-color-scheme applies.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py

CSS = r"""
:root{
  --bg:#EEF3F6; --panel:#FFFFFF; --panel-2:#F6FAFB; --panel-3:#EAF1F4;
  --ink:#14232B; --ink-2:#4A6472; --soft:#76909D;
  --line:#D7E2E8; --line-2:#C3D4DC;
  --plumbob:#2BB534; --plumbob-2:#7CE084; --plumbob-deep:#187A1E;
  --plumbob-ink:#12651A; --plumbob-wash:#E4F7E6;
  --console:#16222A; --console-ink:#CFF5D3; --console-dim:#7FA98A;
  --cheat:#96590A; --cheat-wash:#FBEFD6;
  --warn:#5E7280; --warn-wash:#EBF1F4;
  --shadow:0 1px 2px rgba(20,35,43,.06),0 6px 20px -8px rgba(20,35,43,.18);
  --focus:#0F8FE0;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --bg:#0D1519; --panel:#16222A; --panel-2:#1A2830; --panel-3:#20313A;
    --ink:#E6F0F4; --ink-2:#A3B8C3; --soft:#7B929E;
    --line:#243741; --line-2:#31474F;
    --plumbob:#4FD957; --plumbob-2:#9DF0A3; --plumbob-deep:#2C9433;
    --plumbob-ink:#B4F2B9; --plumbob-wash:#152B19;
    --console:#080E12; --console-ink:#A6ECAD; --console-dim:#5E8A69;
    --cheat:#F2C066; --cheat-wash:#33270E;
    --warn:#9FB4BF; --warn-wash:#1C2A32;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px -10px rgba(0,0,0,.6);
    --focus:#4FB4F5;
  }
}
:root[data-theme="dark"]{
  --bg:#0D1519; --panel:#16222A; --panel-2:#1A2830; --panel-3:#20313A;
  --ink:#E6F0F4; --ink-2:#A3B8C3; --soft:#7B929E;
  --line:#243741; --line-2:#31474F;
  --plumbob:#4FD957; --plumbob-2:#9DF0A3; --plumbob-deep:#2C9433;
  --plumbob-ink:#B4F2B9; --plumbob-wash:#152B19;
  --console:#080E12; --console-ink:#A6ECAD; --console-dim:#5E8A69;
  --cheat:#F2C066; --cheat-wash:#33270E;
  --warn:#9FB4BF; --warn-wash:#1C2A32;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px -10px rgba(0,0,0,.6);
  --focus:#4FB4F5;
}

*{box-sizing:border-box}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font-family:"Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,sans-serif;
  font-size:16.5px; line-height:1.55;
}
.rounded{font-family:ui-rounded,"SF Pro Rounded","Segoe UI Variable Display",
  "Segoe UI",system-ui,sans-serif}
code,kbd,.mono,.cmd{font-family:"Cascadia Mono","Cascadia Code",ui-monospace,
  "SF Mono",Menlo,Consolas,monospace}

/* ---- plumbob ---------------------------------------------------------- */
/* One turn on arrival, then it holds. A permanently spinning mark competes
   with the search field every time you glance at the page. */
.plumbob{position:relative;width:26px;height:36px;flex:0 0 auto;
  animation:drop .5s cubic-bezier(.2,.85,.3,1.25) both}
.plumbob span{position:absolute;left:0;width:100%;display:block;
  animation:turn 1.5s cubic-bezier(.42,0,.2,1) both}
.plumbob .up{top:0;height:58%;
  background:linear-gradient(155deg,var(--plumbob-deep),var(--plumbob-2) 48%,var(--plumbob));
  clip-path:polygon(50% 0,100% 100%,0 100%)}
.plumbob .dn{bottom:0;height:44%;
  background:linear-gradient(25deg,var(--plumbob-deep),var(--plumbob));
  clip-path:polygon(0 0,100% 0,50% 100%)}
@keyframes turn{from{transform:rotateY(0deg)}to{transform:rotateY(360deg)}}
@keyframes drop{from{transform:translateY(-7px);opacity:0}
                to{transform:translateY(0);opacity:1}}
@media (prefers-reduced-motion:reduce){.plumbob,.plumbob span{animation:none}}

/* ---- command bar ------------------------------------------------------ */
.bar{position:sticky;top:0;z-index:10;background:var(--panel);
  border-bottom:1px solid var(--line);box-shadow:var(--shadow)}
.bar-in{width:min(1760px,100%);margin:0 auto;padding:16px 32px;
  display:flex;flex-direction:column;gap:12px}
.brand{display:flex;align-items:center;gap:13px}
.titles{display:flex;flex-direction:column;gap:2px;min-width:0}
.brand h1{margin:0;font-size:25px;font-weight:650;letter-spacing:-.015em}
.brand .by{margin:0;font-size:13px;color:var(--soft)}
.brand .by strong{color:var(--plumbob-ink);font-weight:650}
.brand .sub{margin-left:auto;color:var(--ink-2);font-size:14px;font-weight:600;
  font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.search{position:relative;display:flex;align-items:center}
.search input{width:100%;padding:13px 44px 13px 42px;font-size:16.5px;
  color:var(--ink);background:var(--panel-2);
  border:1.5px solid var(--line-2);border-radius:10px;outline:none;
  font-family:inherit}
.search input::placeholder{color:var(--soft)}
.search input:focus{border-color:var(--plumbob);
  box-shadow:0 0 0 3px var(--plumbob-wash)}
.search .ico{position:absolute;left:15px;color:var(--soft);
  pointer-events:none;font-size:14px}
.search kbd{position:absolute;right:13px;color:var(--soft);font-size:12px;
  border:1px solid var(--line-2);border-radius:5px;padding:1px 6px;
  background:var(--panel-3)}
.search input:not(:placeholder-shown)+.ico+kbd{display:none}
.chips{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.chip{font:inherit;font-size:14px;padding:7px 15px;border-radius:999px;
  border:1px solid var(--line-2);background:var(--panel-2);color:var(--ink-2);
  cursor:pointer;transition:background .12s,border-color .12s,color .12s}
.chip:hover{border-color:var(--plumbob);color:var(--ink)}
.chip[aria-pressed="true"]{background:var(--plumbob-wash);
  border-color:var(--plumbob);color:var(--plumbob-ink);font-weight:600}
.chip:focus-visible,.cmd:focus-visible,.search input:focus-visible{
  outline:2px solid var(--focus);outline-offset:2px}

/* ---- content ---------------------------------------------------------- */
main{width:min(1760px,100%);margin:0 auto;padding:26px 32px 60px;
  display:flex;flex-direction:column;gap:18px}
/* One line, not a paragraph: the measure limit that keeps running prose
   readable just breaks a single UI hint in half. Indented to the cards'
   INNER padding rather than their outer edge - flush against the edge, the
   text sits on the rounded corner of the card below and reads as a misalign. */
.note{color:var(--ink-2);font-size:15px;margin:0 0 0 21px}
/* Cards live inside #list, so main's gap sits around the list rather than
   between them - without this they stack flush and their corners meet. */
#list{display:flex;flex-direction:column;gap:18px}
#list [hidden]{display:none}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  overflow:hidden;box-shadow:var(--shadow)}
.card>header{padding:16px 20px;background:var(--panel-2);
  border-bottom:1px solid var(--line);display:flex;gap:10px;
  align-items:baseline;flex-wrap:wrap}
.card>header h2{margin:0;font-size:18px;font-weight:650;letter-spacing:-.008em}
.card>header .n{margin-left:auto;color:var(--soft);font-size:14px;
  font-variant-numeric:tabular-nums;white-space:nowrap}
.card>header p{margin:0;flex-basis:100%;color:var(--ink-2);font-size:14.5px}
.rows{display:flex;flex-direction:column}
.row{display:grid;gap:22px;padding:12px 20px;
  border-top:1px solid var(--line);align-items:baseline}
.row:first-child{border-top:0}
.row:hover{background:var(--panel-2)}
.desc{color:var(--ink);font-size:15.5px}
.muted{color:var(--ink-2)}
.num{font-variant-numeric:tabular-nums;text-align:right;color:var(--ink-2);
  font-size:14.5px;white-space:nowrap}
.name{font-size:14.5px;color:var(--ink);word-break:break-word}
.who{font-size:14px;color:var(--plumbob-ink);font-weight:600;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cmd{font-size:14.5px;background:var(--console);color:var(--console-ink);
  border:0;border-radius:7px;padding:6px 10px;text-align:left;cursor:pointer;
  line-height:1.4;position:relative;max-width:100%;
  white-space:nowrap;overflow-x:auto;scrollbar-width:thin}
.cmd .arg{color:var(--console-dim)}
.cmd:hover{filter:brightness(1.18)}
.cmd.copied::after{content:"copied";position:absolute;right:8px;top:50%;
  transform:translateY(-50%);font-size:10px;letter-spacing:.06em;
  text-transform:uppercase;color:var(--plumbob-2)}
.flags{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
.flag{font-size:12.5px;letter-spacing:.02em;padding:3px 10px;border-radius:999px;
  white-space:nowrap;font-weight:600}
.f-cheat{background:var(--cheat-wash);color:var(--cheat)}
.f-soft{background:var(--warn-wash);color:var(--warn);font-weight:500;
  font-style:italic}
.f-good{background:var(--plumbob-wash);color:var(--plumbob-ink)}
.empty{padding:52px 20px;text-align:center;color:var(--ink-2)}
.empty strong{display:block;font-size:18px;color:var(--ink);margin-bottom:6px}
footer{width:min(1760px,100%);margin:0 auto;padding:0 32px 60px;
  color:var(--soft);font-size:14px}
footer code{font-size:13px;background:var(--panel-3);padding:1px 6px;
  border-radius:4px;color:var(--ink-2)}
@media (max-width:820px){
  .row{grid-template-columns:1fr !important;gap:7px}
  .flags,.num{justify-content:flex-start;text-align:left}
  .brand .sub{flex-basis:100%;margin-left:0;text-align:left}
}
"""

# Shared front-end helpers. Debounced because the manifest renders thousands of
# rows and toggling `hidden` on every one of them per keystroke is enough work
# to be felt; one frame of latency is not.
SCRIPT = r"""
const esc = s => String(s).replace(/[&<>"']/g, c => ({
  '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function debounce(fn){
  let h = 0;
  return () => { cancelAnimationFrame(h); h = requestAnimationFrame(fn); };
}
function wireChip(btn, apply){
  btn.addEventListener('click', () => {
    btn.setAttribute('aria-pressed',
      btn.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
    apply();
  });
}
function on(btn){ return btn && btn.getAttribute('aria-pressed') === 'true'; }
function wireSearch(q, apply){
  q.addEventListener('input', debounce(apply));
  document.addEventListener('keydown', e => {
    if (e.key === '/' && document.activeElement !== q){
      e.preventDefault(); q.focus(); q.select();
    } else if (e.key === 'Escape' && document.activeElement === q){
      q.value = ''; apply();
    }
  });
}
"""


def bar(title, placeholder, chips_html):
    """The sticky header: plumbob, name, SulSkill credit, live count, search."""
    return f"""<div class="bar">
  <div class="bar-in">
    <div class="brand">
      <div class="plumbob" aria-hidden="true">
        <span class="up"></span><span class="dn"></span>
      </div>
      <div class="titles">
        <h1 class="rounded">{title}</h1>
        <p class="by">Generated by <strong>SulSkill</strong> from the
        installed mods themselves</p>
      </div>
      <div class="sub" id="count">&nbsp;</div>
    </div>
    <div class="search">
      <input id="q" type="search" autocomplete="off" spellcheck="false"
             placeholder="{placeholder}" aria-label="{placeholder}">
      <span class="ico" aria-hidden="true">&#9679;</span>
      <kbd>/</kbd>
    </div>
    <div class="chips" role="group" aria-label="Filters">{chips_html}</div>
  </div>
</div>"""


def page(title, placeholder, chips_html, note_html, body_html, footer_html,
         script, extra_css=''):
    """Assemble a complete report page."""
    return (f'<title>{title}</title>\n<style>{CSS}{extra_css}</style>\n'
            + bar(title, placeholder, chips_html)
            + f"""
<main>
  <p class="note">{note_html}</p>
  {body_html}
  <div class="empty" id="empty" hidden>
    <strong>Nothing matches that</strong>
    <span id="emptyq"></span>
  </div>
</main>

<footer>{footer_html}</footer>

<script>{SCRIPT}{script}</script>
""")
