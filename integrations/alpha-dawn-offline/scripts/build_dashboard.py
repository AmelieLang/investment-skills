"""Build one self-contained HTML file with escaped, public/synthetic demos."""
import base64
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
css=(ROOT/"ui/dashboard.css").read_text(encoding="utf-8")
js=(ROOT/"ui/dashboard.js").read_text(encoding="utf-8")
def csp_hash(text):
    return base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()
def embedded(filename):
    obj=json.loads((ROOT/"examples"/filename).read_text(encoding="utf-8"))
    text=json.dumps(obj,ensure_ascii=False,allow_nan=False)
    return text.replace("&","\\u0026").replace("<","\\u003c").replace(">","\\u003e").replace("\u2028","\\u2028").replace("\u2029","\\u2029")
def contract(path):
    text=json.dumps(json.loads((ROOT/path).read_text(encoding="utf-8")),ensure_ascii=False)
    return text.replace("&","\\u0026").replace("<","\\u003c").replace(">","\\u003e")
csp="default-src 'none'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'; img-src data:; script-src 'sha256-"+csp_hash(js)+"'; style-src 'sha256-"+csp_hash(css)+"'"
panels=[("quality","01","企业质量","固定锚点 · 分析者判断 · 确定性聚合"),("valuation","02","三情景估值","FCFF DCF · 币种与证券单位桥"),("coverage","03","证据需求覆盖","27项预声明需求 · 矛盾不计满足"),("uncertainty","04","不确定性与证伪","事实、假设、反证与阻断条件")]
cards="".join('<section class="panel"><div class="panelHeading"><span class="panelNumber">'+n+'</span><div><h3>'+title+'</h3><small>'+subtitle+'</small></div></div><div class="panelBody" id="'+identifier+'Body"></div></section>' for identifier,n,title,subtitle in panels)
html='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="'''+csp+'''"><title>Alpha Dawn · 离线研究核对台</title><style>'''+css+'''</style></head><body><header><div class="eyebrow">ALPHA DAWN / OFFLINE RESEARCH</div><h1>研究判断，逐项核对</h1><p>质量、估值、证据覆盖与不确定性独立呈现。保留原生方法边界，不生成股票买卖总分。</p><div class="toolbar"><button id="completeButton">完整合成示例</button><button id="historyButton">公共历史缺口</button><label class="fileLabel">导入结果 JSON<input id="fileInput" type="file" accept="application/json,.json"></label></div><div id="message" role="status" aria-live="polite"></div></header><main><div class="caseRow"><div><h2 id="caseName"></h2><div id="dates"></div></div><span class="badge">离线候选 · 无发送与交易能力</span></div><div class="native"><strong id="nativeStatus"></strong><div id="nativeDetail"></div></div><div class="grid">'''+cards+'''</div><div class="audit" id="audit"></div><p class="footer">finterm.ai 原生框架按 MIT 保留许可与版权。质量锚点及 FCFF 适配为我们新增；档位和证据充分性仍需分析者复核。公共历史示例是缺口演示，不是收益回测。</p></main><script type="application/json" id="completeDemo">'''+embedded("synthetic-complete.result.json")+'''</script><script type="application/json" id="historyDemo">'''+embedded("apple-fy2023-public-gaps.result.json")+'''</script><script>'''+js+'''</script></body></html>'''
injected='<script type="application/json" id="resultSchema">'+contract("schema/result.v1.json")+'</script><script type="application/json" id="requirementsContract">'+contract("config/requirements.v1.json")+'</script><script type="application/json" id="riskDemo">'+embedded("synthetic-hard-risk.result.json")+'</script>'
html=html.replace('<script>'+js+'</script>',injected+'<script>'+js+'</script>')
(ROOT/"dashboard.html").write_text(html,encoding="utf-8")
print("Self-contained dashboard built; network CSP=none.")
