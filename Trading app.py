import time
import json
import os
import streamlit as st
import streamlit.components.v1 as components

# 💻 कॉम्पॅक्ट मोबाईल लेआउट सेटिंग्स
st.set_page_config(page_title="NIFTY FLUID DASHBOARD", page_icon="⚡", layout="centered")
st.markdown("<style>.main .block-container { padding: 1rem !important; max-width: 440px !important; }</style>", unsafe_allow_html=True)

# 💾 सेफ डेटा लोडर फंक्शन
def load_live_signal():
    if not os.path.exists('data_signal.json'):
        return {
            'live_spot': 24140.90, 'rsi_v': 34.1, 'ema9': 24149.79, 'nifty_status': '⏳ Waiting',
            'rsi_status': 'FAIL', 'ema_status': 'FAIL', 'vol_status': 'FAIL',
            'runway_status': 'FAIL', 'oi_status': 'FAIL', 'wall_status': 'FAIL',
            'vol_val': '1.0x', 'runway_val': '0 pts', 'oi_val': '1.0x', 'depth_val': '0%',
            'signal_active': False, 'trade_type': 'NONE', 'entry_p': 0.0, 'sl_p': 0.0, 'target_p': 0.0,
            'risk_cash': '0', 'lots_suggested': '0 Lots', 'last_update': '00:00:00'
        }
    try:
        with open('data_signal.json', 'r') as f: return json.load(f)
    except: return st.session_state.get('previous_good_data')

data = load_live_signal()
st.session_state['previous_good_data'] = data

st.title("⚡ NIFTY ALGO LIVE")
st.info(f"📊 NIFTY 50: {data.get('nifty_status', '🔄 Syncing')} | 🕒 Last Update: {data.get('last_update', '00:00:00')}")

rsi_v = data.get('rsi_v', 34.1)
setup = "Pullback" if rsi_v < 50 else "Day High/Low"
t_type = data.get('trade_type', 'NONE')

def check_active(actual, expected):
    return "background:#00e67620;border:1px solid #00e676;color:#00e676;" if actual == expected else "background:#111422;opacity:0.3;color:#8f96a3;"

def map_pass_fail(status_str):
    return '<span style="color:#00e676;font-weight:bold;">[✓ PASS]</span>' if status_str == "PASS" else '<span style="color:#ff5252;font-weight:bold;">[💡 LOCK]</span>'
# 🎫 टार्गेट, एसएल आणि लॉट साईझ डिस्प्ले कार्ड
trade_card_html = ""
if data.get('signal_active', False):
    card_color = "#00e676" if t_type == "CE_BUY" else "#ff5252"
    card_title = "🚀 CE CALL TRIGGERED (BUY)" if t_type == "CE_BUY" else "💥 PE PUT TRIGGERED (BUY)"
    trade_card_html = f"""
    <div style="background:linear-gradient(135deg, {card_color}15, #060814); border:2px solid {card_color}; padding:15px; border-radius:12px; color:white; font-family:-apple-system,BlinkMacSystemFont,sans-serif; margin-top:15px;">
        <div style="display:flex; justify-content:space-between; font-size:12px; color:{card_color}; font-weight:bold; margin-bottom:8px;">
            <span>{card_title}</span>
            <span style="background:{card_color}20; padding:2px 6px; border-radius:4px;">Risk: 2% Max</span>
        </div>
        <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px; text-align:center; margin-bottom:10px;">
            <div style="background:#111422; padding:8px; border-radius:6px; border:1px solid #1c2136;">
                <span style="font-size:10px; color:#8f96a3; display:block;">ENTRY</span>
                <b style="font-size:15px; color:#00e676;">{data.get('entry_p', 0.0):.2f}</b>
            </div>
            <div style="background:#111422; padding:8px; border-radius:6px; border:1px solid #1c2136;">
                <span style="font-size:10px; color:#8f96a3; display:block;">STRUCTURE SL</span>
                <b style="font-size:15px; color:#ff5252;">{data.get('sl_p', 0.0):.2f}</b>
            </div>
            <div style="background:#111422; padding:8px; border-radius:6px; border:1px solid #1c2136;">
                <span style="font-size:10px; color:#8f96a3; display:block;">TARGET (1:2)</span>
                <b style="font-size:15px; color:#ffb300;">{data.get('target_p', 0.0):.2f}</b>
            </div>
        </div>
        <div style="background:#111422; padding:8px; border-radius:6px; font-size:11px; border:1px dashed {card_color}50; text-align:center;">
            🧮 <b>Recommended Size:</b> <span style="color:#00e676; font-weight:bold;">{data.get('lots_suggested', '0 Lots')}</span> | Max Risk Allowed: {data.get('risk_cash', '₹0')}
        </div>
    </div>"""

# 🎨 नवीन टेबल लेआउट रचना (तुमच्या मागणीनुसार मूल्य आणि स्टेटस वेगळे केले)
dhan_card_premium = f"""
<div style="background-color:#060814; padding:15px; border-radius:12px; color:white; border: 1px solid #1c2136; font-family:-apple-system,BlinkMacSystemFont,sans-serif; line-height: 1.4;">
    <div style="font-size:10px; color:#8f96a3; margin-bottom:8px; font-weight:bold;">🐾 DETECTED TECHNICAL SETUP</div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:11px; text-align:center; font-weight:bold; margin-bottom:15px;">
        <div style="{check_active(setup, 'Morning Box')}; padding:6px; border-radius:6px;">Morning Box</div>
        <div style="{check_active(setup, 'Pullback')}; padding:6px; border-radius:6px;">Pullback</div>
        <div style="{check_active(setup, 'Day High/Low')}; padding:6px; border-radius:6px;">Day High/Low</div>
        <div style="{check_active(setup, 'Major Rejection')}; padding:6px; border-radius:6px;">Major Rejection</div>
    </div>
    <div style="background-color:#00e67610; border:1px solid #00e67650; padding:12px; border-radius:10px; text-align:center; margin-bottom:15px;">
        <h1 style="font-size:36px; margin:4px 0; color:#00e676; font-weight:bold;">{data.get('live_spot', 24140.90):.2f}</h1>
    </div>
    
    <div style="font-size:11px; color:#ffb300; margin-bottom:8px; font-weight:bold;">📋 FLUID CRITERIA MATRICES</div>
    <table style="width:100%; font-size:12px; border-collapse:collapse; background:#111422; border-radius:10px; overflow:hidden; border: 1px solid #1c2136;">
        <thead>
            <tr style="background:#1c2136; color:#8f96a3; font-size:10px; text-align:left;">
                <th style="padding:8px;">INDICATOR NAME</th>
                <th style="padding:8px; text-align:center;">VALUE</th>
                <th style="padding:8px; text-align:right;">STATUS</th>
            </tr>
        </thead>
        <tbody>
            <tr style="border-bottom: 1px solid #1c2136;">
                <td style="padding:8px; color:#fff;">1. 5-Min True RSI</td>
                <td style="padding:8px; text-align:center; font-weight:bold; color:#ffb300;">{rsi_v:.1f}</td>
                <td style="padding:8px; text-align:right;">{map_pass_fail(data.get('rsi_status'))}</td>
            </tr>
            <tr style="border-bottom: 1px solid #1c2136;">
                <td style="padding:8px; color:#fff;">2. Institutional 9 EMA</td>
                <td style="padding:8px; text-align:center; font-weight:bold; color:#fff;">{data.get('ema9', 24149.79):.2f}</td>
                <td style="padding:8px; text-align:right;">{map_pass_fail(data.get('ema_status'))}</td>
            </tr>
            <tr style="border-bottom: 1px solid #1c2136;">
                <td style="padding:8px; color:#fff;">3. Volume Tower</td>
                <td style="padding:8px; text-align:center; font-weight:bold; color:#fff;">{data.get('vol_val')}</td>
                <td style="padding:8px; text-align:right;">{map_pass_fail(data.get('vol_status'))}</td>
            </tr>
            <tr style="border-bottom: 1px solid #1c2136;">
                <td style="padding:8px; color:#fff;">4. Runway Breakthrough</td>
                <td style="padding:8px; text-align:center; font-weight:bold; color:#fff;">{data.get('runway_val')}</td>
                <td style="padding:8px; text-align:right;">{map_pass_fail(data.get('runway_status'))}</td>
            </tr>
            <tr style="border-bottom: 1px solid #1c2136;">
                <td style="padding:8px; color:#fff;">5. Option Chain OI Bias</td>
                <td style="padding:8px; text-align:center; font-weight:bold; color:#fff;">{data.get('oi_val')}</td>
                <td style="padding:8px; text-align:right;">{map_pass_fail(data.get('oi_status'))}</td>
            </tr>
            <tr>
                <td style="padding:8px; color:#fff;">6. Order Book Depth Wall</td>
                <td style="padding:8px; text-align:center; font-weight:bold; color:#fff;">{data.get('depth_val')}</td>
                <td style="padding:8px; text-align:right;">{map_pass_fail(data.get('wall_status'))}</td>
            </tr>
        </tbody>
    </table>
    {trade_card_html}
</div>"""

components.html(dhan_card_premium, height=360, scrolling=False)
# 📊 अधिकृत ट्रेडिंगव्ह्यू लाईव्ह चार्ट विजेट (Refused Connection फिक्स रस्ता)
st.markdown("### 📈 NIFTY 50 LIVE CHART")
tradingview_widget = """
<div style="height:350px; width:100%; border-radius:12px; overflow:hidden; border: 1px solid #1c2136;">
    <iframe src="https://tradingview.com" style="display:none;"></iframe>
    <div id="tv-chart-container" style="height:100%; width:100%;"></div>
    <script type="text/javascript" src="https://tradingview.com"></script>
    <script type="text/javascript">
    new TradingView.widget({
      "width": "100%",
      "height": "100%",
      "symbol": "NSE:NIFTY",
      "interval": "5",
      "timezone": "Asia/Kolkata",
      "theme": "dark",
      "style": "1",
      "locale": "in",
      "toolbar_bg": "#f1f3f6",
      "enable_publishing": false,
      "hide_top_toolbar": true,
      "hide_legend": false,
      "save_image": false,
      "container_id": "tv-chart-container"
    });
    </script>
</div>
"""
components.html(tradingview_widget, height=360, scrolling=False)

# ⏱️ स्क्रीन रीफ्रेश रेट (२ सेकंद)
time.sleep(2)
st.rerun()
