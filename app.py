import json
import math
import streamlit as st
from streamlit.components.v1 import html as st_html
import json  # For the JS part

st.set_page_config(layout="wide")

IDC_CHARS = {'⿰', '⿱', '⿲', '⿳', '⿴', '⿵', '⿶', '⿷', '⿸', '⿹', '⿺', '⿻'}

def apply_dynamic_css():
    css = """
    <style>
        /* 1. SIDEBAR: Results Count Header */
        .results-header-sidebar {
            font-size: 1.4em;
            font-weight: bold;
            color: #2c3e50;
            margin: 20px 0 10px 0;
            text-align: center;
        }

        /* 2. SIDEBAR: The Big Red Selected Character */
        .selected-char-sidebar {
            font-size: 3em; 
            text-align: center;
            color: #e74c3c; 
            margin: 20px 0;
            font-weight: bold;
        }

        /* NEW: SIDEBAR PREVIEW STYLES */
        .preview-char-sidebar {
            font-size: 2.8em;
            text-align: center;
            color: #e74c3c;
            margin: 15px 0 10px 0;
            font-weight: bold;
        }
        .preview-details-sidebar {
            font-size: 1.05em;
            line-height: 1.5;
            color: #2c3e50;
            background: #f8f9fa;
            padding: 12px;
            border-radius: 8px;
            border: 1px solid #e0e0e0;
        }

        /* 3. RESULTS: The White Description Card */
        .char-card {
            background: white;
            padding: 18px;
            border-radius: 10px;
            margin-bottom: 0px; 
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            height: 100%; 
            display: flex;
            align-items: center;
        }

        /* 4. BROWSING GRID: Large Tiles */
        .comp-grid .stButton button {
            font-size: 2em;
            height: 80px;
            background: white;
            border: 1px solid #e0e0e0;
            border-radius: 12px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.08);
            padding: 0;
            line-height: 80px;
        }
        .comp-grid .stButton button:hover {
            background: #fff5f5;
            border-color: #f2c6c6;
            color: #c0392b;
        }

        /* 5. INSTRUCTIONS: The Green Status Line */
        .status-line {
            font-size: 1.1em;
            font-weight: 600;
            color: #0f5132;
            background-color: #d1e7dd;
            border: 1px solid #badbcc;
            padding: 15px;
            border-radius: 8px;
            margin: 20px 0 30px 0;
            text-align: center;
        }

        /* NEW: Preview count line in browsing mode */
        .preview-count-line {
            font-size: 1.3em;
            text-align: center;
            color: #2c3e50;
            margin: 20px 0 25px 0;
        }
        .preview-count-line .char {
            font-size: 1.4em;
            font-weight: bold;
            color: #2c3e50;
        }

        /* Jump input at bottom */
        .jump-footer {
            margin-top: 40px;
            padding: 20px;
            background: #f8f9fa;
            border-top: 1px solid #e0e0e0;
            text-align: center;
        }
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)

@st.cache_data
def load_component_map():
    try:
        with open("enhanced_component_map_with_etymology.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        return {}

try:
    component_map = load_component_map()
except Exception as e:
    component_map = {}
    st.error(f"Failed to load data: {e}")

def clean_field(field):
    return field[0] if isinstance(field, list) and field else field or "—"

def get_stroke_count(char):
    strokes = component_map.get(char, {}).get("meta", {}).get("strokes", None)
    try:
        if isinstance(strokes, (int, float)) and strokes > 0: return int(strokes)
        if isinstance(strokes, str) and strokes.isdigit(): return int(strokes)
    except: pass
    return None

def get_etymology_text(meta):
    etymology = meta.get("etymology", {})
    hint = clean_field(etymology.get("hint", "No hint"))
    details = clean_field(etymology.get("details", ""))
    return f"{hint}{'; ' + details if details and details != '—' else ''}"

def format_decomposition(char):
    d = component_map.get(char, {}).get("meta", {}).get("decomposition", "")
    return "—" if not d or '?' in d else d

# State init
defaults = {
    "selected_comp": "", "stroke_count": 0, "radical": "none", "component_idc": "none",
    "display_mode": "Single Character", "text_input_comp": "", "page": 1, "text_input_warning": None,
    "show_inputs": True, "last_valid_selected_comp": "", "preview_comp": None,
    "stroke_view_active": False, "stroke_view_char": ""
}
for k, v in defaults.items():
    if k not in st.session_state: st.session_state[k] = v

# Callbacks
def sync_stroke():
    val = st.session_state.w_stroke
    st.session_state.stroke_count = int(val) if val != 0 else 0
    st.session_state.page = 1

def sync_radical():
    st.session_state.radical = st.session_state.w_radical
    st.session_state.page = 1

def sync_idc():
    st.session_state.component_idc = st.session_state.w_idc
    st.session_state.page = 1

def sync_display():
    st.session_state.display_mode = st.session_state.w_display

def sync_text():
    v = st.session_state.w_text.strip()
    if len(v) != 1:
        st.session_state.text_input_warning = "One character only"
        return
    if v in component_map:
        st.session_state.selected_comp = v
        st.session_state.last_valid_selected_comp = v
        st.session_state.text_input_comp = v
        st.session_state.text_input_warning = None
        st.session_state.show_inputs = False
        st.session_state.preview_comp = None
    else:
        st.session_state.text_input_warning = "Not found"

def tile_click(c):
    if st.session_state.show_inputs:
        # In browsing mode: single click → preview in sidebar
        if st.session_state.preview_comp == c:
            # Second click → commit to full results view
            st.session_state.selected_comp = c
            st.session_state.last_valid_selected_comp = c
            st.session_state.show_inputs = False
            st.session_state.preview_comp = None
            st.session_state.text_input_comp = c  # Sync jump input
        else:
            # First click → preview
            st.session_state.preview_comp = c
    else:
        pass

def back():
    st.session_state.show_inputs = True
    st.session_state.preview_comp = None
    st.session_state.stroke_view_active = False
    st.session_state.stroke_view_char = ""
    st.session_state.text_input_comp = ""          # Clear jump input
    st.session_state.text_input_warning = None

def end_stroke_view():
    st.session_state.stroke_view_active = False
    st.session_state.stroke_view_char = ""

def reset():
    st.session_state.stroke_count = 0
    st.session_state.radical = "none"
    st.session_state.component_idc = "none"
    st.session_state.page = 1
    st.session_state.show_inputs = True
    st.session_state.preview_comp = None
    st.session_state.stroke_view_active = False
    st.session_state.stroke_view_char = ""
    st.session_state.text_input_comp = ""
    st.session_state.text_input_warning = None

def render_sidebar_preview(c):
    if not c or c not in component_map:
        return

    related = component_map.get(c, {}).get("related_characters", [])
    chars_unique = list(set([ch for ch in related if len(ch) == 1]))
    count = len(chars_unique)

    meta = component_map.get(c, {}).get("meta", {})
    f = {
        "Pinyin": clean_field(meta.get("pinyin", "—")),
        "Strokes": f"{get_stroke_count(c)} strokes" if get_stroke_count(c) else "unknown",
        "Radical": clean_field(meta.get("radical", "—")),
        "Decomposition": format_decomposition(c),
        "Definition": clean_field(meta.get("definition", "—")),
        "Etymology": get_etymology_text(meta),
    }
    details = " · ".join(f"<strong>{k}:</strong> {v}" for k, v in f.items())

    st.markdown(
        f"<div class='preview-count-line'>{count} characters with <span class='char'>{c}</span></div>",
        unsafe_allow_html=True
    )

    st.markdown(f"<div style='font-size:1.05em;line-height:1.5;color:#2c3e50;background:#f8f9fa;padding:12px;border-radius:8px;border:1px solid #e0e0e0;'>{details}</div>", unsafe_allow_html=True)

def render_stroke_order_view(char: str):
    char = (char or "").strip()
    char = char[0] if char else ""

    if not char:
        st.info("No character selected for stroke order.")
        return

    st.markdown(f"## Stroke order — {char}")

    st_html(
        f"""
        <div style="display:flex; gap:24px; align-items:flex-start; flex-wrap:wrap;">
          <div>
            <div id="hw-target" style="width:420px;height:420px;border:1px solid #e0e0e0;border-radius:12px;"></div>
            <div style="margin-top:12px; display:flex; gap:8px; flex-wrap:wrap;">
              <button id="hw-prev">Back</button>
              <button id="hw-next">Next</button>
              <button id="hw-reset">Reset</button>
              <button id="hw-animate">Animate</button>
            </div>
            <div id="hw-status" style="margin-top:10px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color:#444;"></div>
            <div id="hw-error" style="margin-top:10px; color:#b00020;"></div>
          </div>
        </div>

        <script>
          (function() {{
            const char = {json.dumps(char, ensure_ascii=False)};

            const statusEl = document.getElementById('hw-status');
            const errEl = document.getElementById('hw-error');

            function loadScript(src) {{
              return new Promise((resolve, reject) => {{
                const s = document.createElement('script');
                s.src = src;
                s.async = true;
                s.onload = () => resolve(src);
                s.onerror = () => {{
                  try {{ s.remove(); }} catch(e) {{}}
                  reject(new Error(`Failed to load script: ${{src}}`));
                }};
                document.head.appendChild(s);
              }});
            }}

            async function ensureLibLoaded() {{
              if (window.HanziWriter) return;

              const sources = [
                'https://cdn.jsdelivr.net/npm/hanzi-writer@3/dist/hanzi-writer.min.js',
                'https://unpkg.com/hanzi-writer@3/dist/hanzi-writer.min.js'
              ];

              let lastErr = null;
              for (const src of sources) {{
                try {{
                  await loadScript(src);
                  if (window.HanziWriter) return;
                }} catch (e) {{
                  lastErr = e;
                }}
              }}
              throw new Error('Failed to load HanziWriter library. All configured CDNs were unreachable.');
            }}

            const dataUrls = [
              `https://cdn.jsdelivr.net/npm/hanzi-writer-data@2.0.1/${{char}}.json`,
              `https://unpkg.com/hanzi-writer-data@2.0.1/${{char}}.json`
            ];

            async function loadCharData() {{
              for (const url of dataUrls) {{
                try {{
                  const res = await fetch(url);
                  if (!res.ok) continue;
                  return await res.json();
                }} catch (e) {{
                }}
              }}
              throw new Error('Stroke data not found for this character in hanzi-writer-data.');
            }}

            let writer = null;
            let i = -1;
            let total = 0;

            function setStatus() {{
              statusEl.textContent = `Stroke: ${{Math.max(i+1, 0)}} / ${{total}}`;
            }}

            async function init() {{
              try {{
                await ensureLibLoaded();
                const charData = await loadCharData();
                total = (charData.medians || []).length || 0;

                writer = window.HanziWriter.create('hw-target', char, {{
                  width: 420,
                  height: 420,
                  padding: 14,
                  showOutline: true,
                  showCharacter: false,
                  strokeAnimationSpeed: 1,
                  delayBetweenStrokes: 120,
                  charDataLoader: () => Promise.resolve(charData)
                }});

                i = -1;
                writer.hideCharacter();
                setStatus();
              }} catch (e) {{
                errEl.textContent = e && e.message ? e.message : String(e);
              }}
            }}

            async function nextStroke() {{
              if (!writer) return;
              if (i + 1 >= total) return;
              i += 1;
              await writer.animateStroke(i);
              setStatus();
            }}

            async function prevStroke() {{
              if (!writer) return;
              if (i <= -1) return;
              i -= 1;
              writer.hideCharacter();
              for (let k = 0; k <= i; k++) {{
                await writer.animateStroke(k);
              }}
              setStatus();
            }}

            function resetAll() {{
              if (!writer) return;
              i = -1;
              writer.hideCharacter();
              setStatus();
            }}

            async function animateAll() {{
              if (!writer) return;
              i = -1;
              writer.hideCharacter();
              await writer.animateCharacter();
              i = total - 1;
              setStatus();
            }}

            document.getElementById('hw-next').addEventListener('click', nextStroke);
            document.getElementById('hw-prev').addEventListener('click', prevStroke);
            document.getElementById('hw-reset').addEventListener('click', resetAll);
            document.getElementById('hw-animate').addEventListener('click', animateAll);

            init();
          }})();
        </script>
        """,
        height=560,
    )

def main():
    if not component_map:
        st.stop()

    apply_dynamic_css()

    # === SIDEBAR ===
    with st.sidebar:
        st.markdown("<h1 style='text-align:center; margin-bottom:30px;'>🈑 Radix</h1>", unsafe_allow_html=True)

        # Prominent Reset button always visible
        if st.button("🔄 Reset All Filters & Selection", use_container_width=True, type="primary"):
            reset()
            st.rerun()

      

        if st.session_state.stroke_view_active:
            st.button("← Back", on_click=end_stroke_view, use_container_width=True)
            st.button("← Back to list", on_click=back, use_container_width=True)

        elif st.session_state.show_inputs:
            # Browsing mode - Filters only
            st.markdown("### Filters")

            stroke_set = {s for s in (get_stroke_count(c) for c in component_map) if isinstance(s, int)}
            stroke_opts = [0] + sorted(stroke_set)
            current = st.session_state.stroke_count if isinstance(st.session_state.stroke_count, int) and st.session_state.stroke_count in stroke_opts else 0
            st.selectbox("Strokes", options=stroke_opts, index=stroke_opts.index(current),
                         format_func=lambda x: "Any" if x == 0 else str(x), key="w_stroke", on_change=sync_stroke)

            rad_set = {component_map.get(c, {}).get("meta", {}).get("radical", "") for c in component_map if component_map.get(c, {}).get("meta", {}).get("radical")}
            rad_opts = ["none"] + sorted(rad_set)
            st.selectbox("Radical", options=rad_opts, index=rad_opts.index(st.session_state.radical), key="w_radical", on_change=sync_radical)

            idc_set = {d[0] for d in (component_map.get(c, {}).get("meta", {}).get("decomposition", "") for c in component_map) if d and d[0] in IDC_CHARS}
            idc_opts = ["none"] + sorted(idc_set)
            st.selectbox("Structure", options=idc_opts, index=idc_opts.index(st.session_state.component_idc), key="w_idc", on_change=sync_idc)

            st.markdown("---")
            # Preview in sidebar when browsing
            if st.session_state.preview_comp:
                render_sidebar_preview(st.session_state.preview_comp)

        else:
            # Results mode sidebar
            st.button("← Back to list", on_click=back, use_container_width=True)

            so_char = (st.session_state.selected_comp or "").strip()[:1]
            if so_char and st.button("View stroke order", use_container_width=True):
                st.session_state.stroke_view_char = so_char
                st.session_state.stroke_view_active = True
                st.rerun()

            # Large red character
            st.markdown(f"<div class='selected-char-sidebar'>{st.session_state.selected_comp}</div>", unsafe_allow_html=True)

            # Count line
            related = component_map[st.session_state.selected_comp].get("related_characters", [])
            chars_unique = list(set([c for c in related if len(c) == 1]))
            n = int(st.session_state.display_mode[0]) if st.session_state.display_mode != "Single Character" else 0
            compounds = {c: [w for w in component_map.get(c, {}).get("meta", {}).get("compounds", []) if len(w)==n] for c in chars_unique}
            valid_chars = [c for c in chars_unique if n == 0 or compounds[c]]
            count = len(valid_chars)

            st.markdown(
                f"<div class='count-line'>{count} characters with <span class='char'>{st.session_state.selected_comp}</span></div>",
                unsafe_allow_html=True
            )

            modes = ["Single Character", "2-Character Phrases", "3-Character Phrases", "4-Character Phrases"]
            st.radio("", options=modes, index=modes.index(st.session_state.display_mode), key="w_display", on_change=sync_display)

    # === MAIN CONTENT ===
    if st.session_state.stroke_view_active:
        render_stroke_order_view(st.session_state.stroke_view_char)
        return

    if st.session_state.show_inputs:
        # Browsing mode
        filter_parts = []
        if st.session_state.stroke_count > 0:
            filter_parts.append(f"{st.session_state.stroke_count} strokes")
        if st.session_state.radical != "none":
            filter_parts.append(f"Radical: {st.session_state.radical}")
        if st.session_state.component_idc != "none":
            filter_parts.append(f"Structure: {st.session_state.component_idc}")

        filter_summary = " · ".join(filter_parts) if filter_parts else "none"
        instruction = "Click once to preview in sidebar · Click twice to explore characters"
        st.markdown(f"<div class='status-line'>Filtered: {filter_summary} — {instruction}</div>", unsafe_allow_html=True)

        filtered = [c for c in component_map if
            (st.session_state.stroke_count == 0 or get_stroke_count(c) == st.session_state.stroke_count) and
            (st.session_state.radical == "none" or component_map.get(c, {}).get("meta", {}).get("radical") == st.session_state.radical) and
            (st.session_state.component_idc == "none" or component_map.get(c, {}).get("meta", {}).get("decomposition", "").startswith(st.session_state.component_idc))
        ]

        def _result_count(comp: str) -> int:
            rel = component_map.get(comp, {}).get("related_characters", [])
            return len({x for x in rel if isinstance(x, str) and len(x) == 1})

        _counts = {c: _result_count(c) for c in filtered}
        sorted_comps = sorted(filtered, key=lambda c: (-_counts.get(c, 0), get_stroke_count(c) or 999, c))

        if not sorted_comps:
            st.info("No components match current filters.")
            return

        PAGE_SIZE = 120
        GRID_COLS = 10
        total = len(sorted_comps)
        max_page = max(1, math.ceil(total / PAGE_SIZE))
        st.session_state.page = max(1, min(st.session_state.page, max_page))

        p1, p2, p3 = st.columns([1, 3, 1])
        with p1:
            if st.button("◀ Prev", disabled=st.session_state.page<=1):
                st.session_state.page -= 1
        with p2:
            start = (st.session_state.page-1)*PAGE_SIZE + 1
            end = min(st.session_state.page*PAGE_SIZE, total)
            st.markdown(f"<div style='text-align:center; padding:10px 0; font-size:1.1em; color:#555;'>{start}–{end} of {total}</div>", unsafe_allow_html=True)
        with p3:
            if st.button("Next ▶", disabled=st.session_state.page>=max_page):
                st.session_state.page += 1

        page = sorted_comps[(st.session_state.page-1)*PAGE_SIZE : st.session_state.page*PAGE_SIZE]
        st.markdown("<div class='comp-grid'>", unsafe_allow_html=True)
        cols = st.columns(GRID_COLS)
        for i, ch in enumerate(page):
            with cols[i % GRID_COLS]:
                is_preview = st.session_state.preview_comp == ch
                st.button(ch, key=f"b_{ch}_{st.session_state.page}", use_container_width=True,
                          type="primary" if is_preview else "secondary", on_click=tile_click, args=(ch,))
        st.markdown("</div>", unsafe_allow_html=True)

        # === JUMP INPUT AT BOTTOM (only in browsing mode) ===
        st.markdown("<div class='jump-footer'>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.session_state.text_input_warning:
                st.warning(st.session_state.text_input_warning)
            st.text_input(
                "Jump to character",
                value=st.session_state.text_input_comp,
                key="w_text",
                on_change=sync_text,
                placeholder="Type a single Hanzi, e.g. 水",
                label_visibility="collapsed"
            )
            st.caption("Enter one Chinese character to jump directly to its details")
        st.markdown("</div>", unsafe_allow_html=True)

    else:
        # Results mode
        related = component_map[st.session_state.selected_comp].get("related_characters", [])
        chars = list(set([c for c in related if len(c)==1]))
        n = int(st.session_state.display_mode[0]) if st.session_state.display_mode != "Single Character" else 0
        compounds = {c: [w for w in component_map.get(c, {}).get("meta", {}).get("compounds", []) if len(w)==n] for c in chars} if n else {c:[] for c in chars}
        chars = [c for c in chars if n==0 or compounds[c]]

        for c in sorted(chars, key=lambda x: get_stroke_count(x) or 999):

            # --- per-card actions row ---
            a1, a2 = st.columns([2, 8], vertical_alignment="center")

            with a1:
                if st.button("Stroke order", key=f"stroke_{c}", use_container_width=True):
                    st.session_state.stroke_view_char = c[:1]
                    st.session_state.stroke_view_active = True
                    st.rerun()

            with a2:
                # keep your existing card rendering here
                meta = component_map.get(c, {}).get("meta", {})
                fd = {
                    "Pinyin": clean_field(meta.get("pinyin", "—")),
                    "Strokes": f"{get_stroke_count(c)} strokes" if get_stroke_count(c) else "unknown",
                    "Definition": clean_field(meta.get("definition", "—")),
                    "Radical": clean_field(meta.get("radical", "—")),
                    "Decomposition": clean_field(meta.get("decomposition", "—")),
                }

                st.markdown(
                    f"""
                    <div style="border:1px solid #eee; border-radius:12px; padding:12px; background:#fff;">
                    <div style="display:flex; gap:14px; align-items:flex-start;">
                        <div style="font-size:44px; line-height:1;">{c}</div>
                        <div style="flex:1;">
                        <div style="display:grid; grid-template-columns: 120px 1fr; row-gap:4px; column-gap:10px;">
                            <div><b>Pinyin</b></div><div>{fd["Pinyin"]}</div>
                            <div><b>Strokes</b></div><div>{fd["Strokes"]}</div>
                            <div><b>Radical</b></div><div>{fd["Radical"]}</div>
                            <div><b>Decomposition</b></div><div>{fd["Decomposition"]}</div>
                            <div><b>Definition</b></div><div>{fd["Definition"]}</div>
                        </div>
                        </div>
                    </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        if chars and n:
            with st.expander("Export Compounds"):
                st.text_area("Copy list", "\n".join(w for c in chars for w in compounds[c]), height=150)

if __name__ == "__main__":
    main()
