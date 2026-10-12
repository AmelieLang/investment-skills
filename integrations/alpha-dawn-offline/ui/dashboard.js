/* Offline renderer. All imported/source content is text; there are no network APIs. */
"use strict";
const $ = id => document.getElementById(id);
const cache = new Map();
let current = null, selectedScenario = "base";
const names = {bear:"悲观",base:"基准",bull:"乐观"};
function node(tag, text, className) {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = String(text);
  if (className) e.className = className;
  return e;
}
function finiteTree(v, depth=0) {
  if (depth>40) throw new Error("JSON 嵌套过深");
  if (typeof v==="number" && !Number.isFinite(v)) throw new Error("拒绝非有限数值");
  if (v && typeof v==="object") Object.values(v).forEach(x=>finiteTree(x,depth+1));
}
function parseStrict(text) {
  if (new TextEncoder().encode(text).length>2000000) throw new Error("文件超过 2 MB");
  let pos=0;
  const ws=()=>{while (/\s/.test(text[pos]||"") && pos<text.length) pos++;};
  function string() {
    const pattern=/"(?:[^"\\\u0000-\u001f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"/y;
    pattern.lastIndex=pos; const m=pattern.exec(text);
    if (!m) throw new Error("非法字符串");
    pos=pattern.lastIndex; return JSON.parse(m[0]);
  }
  function value(depth=0) {
    if(depth>40) throw new Error("JSON 嵌套过深");
    ws(); const c=text[pos];
    if(c==='"') return string();
    if(c==='{') {
      pos++; ws(); const out=Object.create(null), keys=new Set();
      if(text[pos]==='}') {pos++;return out;}
      while(true) {
        ws(); const key=string(); if(keys.has(key)) throw new Error("重复 JSON 键："+key);
        keys.add(key);ws();if(text[pos++]!==':') throw new Error("缺少冒号");
        out[key]=value(depth+1);ws();const sep=text[pos++];
        if(sep==='}') return out; if(sep!==',') throw new Error("非法对象");
      }
    }
    if(c==='[') {
      pos++;ws();const out=[];if(text[pos]===']'){pos++;return out;}
      while(true){out.push(value(depth+1));ws();const sep=text[pos++];if(sep===']')return out;if(sep!==',')throw new Error("非法数组");}
    }
    for(const [literal,v] of [["true",true],["false",false],["null",null]]) {
      if(text.slice(pos,pos+literal.length)===literal){pos+=literal.length;return v;}
    }
    const pattern=/-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/y;pattern.lastIndex=pos;
    const m=pattern.exec(text);if(!m)throw new Error("非法 JSON 值");pos=pattern.lastIndex;
    const n=Number(m[0]);if(!Number.isFinite(n))throw new Error("拒绝非有限数值");return n;
  }
  const out=value();ws();if(pos!==text.length)throw new Error("JSON 尾部多余内容");return out;
}
function canonical(v) {
  if(Array.isArray(v)) return "["+v.map(canonical).join(",")+"]";
  if(v && typeof v==="object") return "{"+Object.keys(v).sort().map(k=>JSON.stringify(k)+":"+canonical(v[k])).join(",")+"}";
  return JSON.stringify(v);
}
function validateSchema(value, schema, defs, location="$", depth=0) {
  if(depth>40)throw new Error("契约嵌套过深："+location);
  if(schema.$ref)return validateSchema(value,defs[schema.$ref.split("/").pop()],defs,location,depth+1);
  const types=Array.isArray(schema.type)?schema.type:schema.type?[schema.type]:[];
  const matches={object:value!==null&&typeof value==="object"&&!Array.isArray(value),array:Array.isArray(value),string:typeof value==="string",number:typeof value==="number"&&Number.isFinite(value),integer:Number.isInteger(value),boolean:typeof value==="boolean",null:value===null};
  if(types.length&&!types.some(t=>matches[t]))throw new Error("契约类型错误："+location);
  if(Object.hasOwn(schema,"const")&&canonical(value)!==canonical(schema.const))throw new Error("契约常量不匹配："+location);
  if(schema.enum&&!schema.enum.some(v=>canonical(v)===canonical(value)))throw new Error("契约枚举错误："+location);
  if(matches.object){
    const props=schema.properties||Object.create(null);
    for(const key of schema.required||[])if(!Object.hasOwn(value,key))throw new Error("缺少必需字段："+location+"."+key);
    for(const [key,item]of Object.entries(value)){
      const child=Object.hasOwn(props,key)?props[key]:schema.additionalProperties===undefined?{}:schema.additionalProperties;
      if(child===false)throw new Error("未声明字段："+location+"."+key);
      if(child&&typeof child==="object")validateSchema(item,child,defs,location+"."+key,depth+1);
    }
  }
  if(matches.array){if(value.length<(schema.minItems||0)||value.length>(schema.maxItems??10000))throw new Error("契约数组长度："+location);value.forEach((x,i)=>validateSchema(x,schema.items||{},defs,location+"["+i+"]",depth+1));}
  if(matches.string){
    if(value.length<(schema.minLength||0)||value.length>(schema.maxLength??100000))throw new Error("契约文本长度："+location);
    if(schema.pattern&&!new RegExp("^(?:"+schema.pattern+")$").test(value))throw new Error("契约模式错误："+location);
    if(schema.format==="date"||schema.format==="date-time"){
      const m=/^(\d{4})-(\d{2})-(\d{2})/.exec(value),d=m&&new Date(Date.UTC(+m[1],+m[2]-1,+m[3]));
      if(!m||d.getUTCFullYear()!==+m[1]||d.getUTCMonth()+1!==+m[2]||d.getUTCDate()!==+m[3]||(schema.format==="date"&&value.length!==10)||(schema.format==="date-time"&&(!/(Z|[+-]\d{2}:\d{2})$/.test(value)||!Number.isFinite(Date.parse(value)))))throw new Error("契约日期错误："+location);
    }
  }
  if(matches.number&&(value<(schema.minimum??-Infinity)||value>(schema.maximum??Infinity)))throw new Error("契约数值域："+location);
}
function validateResult(r) {
  finiteTree(r);
  const schema=parseStrict($("resultSchema").textContent);
  validateSchema(r,schema,schema.$defs);
  if(!r || r.schema_version!=="offline-alpha-dawn/v1.1" || r.bot_id!=="alpha-dawn-framework" || !/^[0-9a-f]{64}$/.test(r.result_id||"")) throw new Error("不是本适配器的结果文件");
  for(const key of ["quality","valuation","evidence_coverage","uncertainty","native_output"]) if(!r[key] || typeof r[key]!=="object" || Array.isArray(r[key]))throw new Error("缺少结果块："+key);
  if(r.method_manifest?.commit!=="7235d3411601036cc79137fa0aec0d587f2c8e19")throw new Error("方法 commit 不匹配");
  if(!Array.isArray(r.quality.components)||r.quality.components.length!==5)throw new Error("质量分项不完整");
  if(!Array.isArray(r.valuation.scenarios)||r.valuation.scenarios.length!==3||new Set(r.valuation.scenarios.map(x=>x.name)).size!==3)throw new Error("情景不完整或重复");
  if(r.evidence_coverage.declared!==27||!Array.isArray(r.evidence_coverage.requirements)||r.evidence_coverage.requirements.length!==27)throw new Error("需求清单不匹配");
  if(!r.capabilities||["network","send","trade","execute_source_text"].some(k=>r.capabilities[k]!==false))throw new Error("拒绝具有发送、交易或执行能力的结果");
  if(r.quality.components.some(c=>c.score!==null&&(!Number.isInteger(c.score)||c.score<0||c.score>4)))throw new Error("档位范围错误");
  const expected=[["economics",25],["moat",20],["capital",25],["resilience",15],["governance",15]],q=r.quality;
  if(q.components.some((c,i)=>c.id!==expected[i][0]||c.weight!==expected[i][1]))throw new Error("分项或固定权重不匹配");
  const contribution=q.components.reduce((n,c)=>n+(c.score===null?0:c.weight*c.score/4),0),observed=q.components.reduce((n,c)=>n+(c.score===null?0:c.weight),0);
  if(q.observed_contribution!==contribution||q.observed_weight!==observed||q.possible_range?.[0]!==contribution||q.possible_range?.[1]!==contribution+100-observed)throw new Error("聚合值或缺失区间不一致");
  if(canonical(q.hard_risks)!==canonical(r.uncertainty.hard_risks))throw new Error("硬风险记录不一致");
  const critical=q.hard_risks.some(x=>x.status==="confirmed"&&x.verified_for_adapter===true);
  const expectedStatus=critical?"blocked_by_hard_risk":observed<100?"partial":"complete";
  if(q.status!==expectedStatus)throw new Error("硬风险或缺失状态不一致");
  const expectedTotal=observed<100||critical?null:contribution;
  if(q.total!==expectedTotal||q.arithmetic_total!==(observed<100?null:contribution))throw new Error("总分与独立分项不一致");
  const cov=r.evidence_coverage;
  if(cov.requirements.some(x=>typeof x.satisfied!=="boolean"||x.weight!==1)||new Set(cov.requirements.map(x=>x.id)).size!==27||cov.satisfied!==cov.requirements.filter(x=>x.satisfied).length||Math.abs(cov.ratio-cov.satisfied/27)>1e-12)throw new Error("证据覆盖计数不一致");
  if(r.valuation.scenarios.map(x=>x.name).sort().join(",")!=="base,bear,bull")throw new Error("情景名称错误");
  const contract=parseStrict($("requirementsContract").textContent),frozen=new Map(contract.items.map(x=>[x.id,x]));
  const facts=new Map();for(const f of r.evidence_receipt){if(facts.has(f.id))throw new Error("重复事实ID");facts.set(f.id,f);}
  const ineligible=new Set(r.uncertainty.ineligible_facts.map(x=>x.id));
  for(const row of cov.requirements){const wanted=frozen.get(row.id);if(!wanted||row.group!==wanted.group||row.title!==wanted.title||row.criterion!==wanted.criterion)throw new Error("冻结需求ID或分组不一致");
    if(row.evidence_ids.some(id=>!facts.has(id)))throw new Error("需求引用未知事实");
    if(row.satisfied&&(!row.evidence_ids.length||row.window_status==="unmet"||row.evidence_ids.some(id=>ineligible.has(id)||facts.get(id).value===null||!facts.get(id).source.available)))throw new Error("未满足证据被计入覆盖率");}
  for(const [group,count]of [["quality",15],["dcf",8],["comparison",4]]){const rows=cov.requirements.filter(x=>x.group===group);if(rows.length!==count||cov.modules[group].declared!==count||cov.modules[group].satisfied!==rows.filter(x=>x.satisfied).length)throw new Error("分组覆盖计数错误");}
  if(cov.document_availability.declared_fact_sources!==r.evidence_receipt.length||cov.document_availability.available!==r.evidence_receipt.filter(x=>x.source.available).length)throw new Error("文档可获取计数错误");
  for(const s of r.valuation.scenarios){
    const nonpositive=(s.quote_value!==null&&s.quote_value<=0)||(s.price!==undefined&&s.price<=0);
    if(nonpositive&&(s.upside_vs_price!==null||s.margin_to_model_value!==null||s.comparison_status!=="nonpositive_domain"||!s.diagnostics.some(d=>d.code==="NONPOSITIVE_COMPARISON_DOMAIN")))throw new Error("非正模型值/报价不得产生比较比率");
    if(s.comparison_status==="computed"&&(!(s.quote_value>0)||!(s.price>0)||s.upside_vs_price===null||s.margin_to_model_value===null))throw new Error("比较域或结果不完整");
    if(s.comparison_status!=="computed"&&(s.upside_vs_price!==null||s.margin_to_model_value!==null))throw new Error("不可比较结果包含比率");
    if(s.comparison_status==="computed"&&(Math.abs(s.upside_vs_price-(s.quote_value/s.price-1))>1e-10||Math.abs(s.margin_to_model_value-((s.quote_value-s.price)/s.quote_value))>1e-10))throw new Error("比较比率不一致");
  }
  return r;
}
function metric(label, value, suffix="") {
  const box=node("div",undefined,"metric");box.append(node("span",label,"muted"),node("strong",value===null?"不可计算":value+suffix));return box;
}
function amount(v, currency, unit="") {
  if(v===null||v===undefined) return "不可计算";
  const absolute=Math.abs(v), million=absolute>=1000000;
  return new Intl.NumberFormat("zh-CN",{maximumFractionDigits:million?2:3}).format(million?v/1000000:v)+" "+currency+(million?" 百万":"")+unit;
}
function pct(v){return v===null||v===undefined?"不可比较":new Intl.NumberFormat("zh-CN",{style:"percent",maximumFractionDigits:1}).format(v);}
function detail(title, content){const d=node("details");d.append(node("summary",title));const pre=node("pre",typeof content==="string"?content:JSON.stringify(content,null,2));d.append(pre);return d;}
function progress(value,max){const p=node("progress");p.max=max;p.value=value;return p;}
function table(headers,rows){const t=node("table"),head=node("thead"),tr=node("tr");headers.forEach(h=>tr.append(node("th",h)));head.append(tr);t.append(head);const body=node("tbody");rows.forEach(cells=>{const row=node("tr");cells.forEach(cell=>row.append(node("td",cell)));body.append(row);});t.append(body);return t;}
function render(r) {
  current=r;
  $("caseName").textContent=r.case_id==="synthetic-complete"?"合成企业 · 完整输入":r.case_id==="apple-fy2023-public-gaps"?"Apple FY2023 · 公共资料缺口":r.case_id==="synthetic-hard-risk"?"合成企业 · 严重偿付风险":r.case_id;
  $("dates").textContent="信息截止 "+r.cutoff_at+" · 估值日 "+r.valuation_date;
  $("nativeStatus").textContent="原生状态："+(r.native_output.status||"未声明")+" · 新增结果独立计算";
  $("nativeDetail").replaceChildren(detail("查看原生输出与方法版本（原样保留）",{native_output:r.native_output,native_output_hash:r.native_output_hash,method:r.method_manifest.repository,commit:r.method_manifest.commit,license:r.method_manifest.license}));
  const q=r.quality, qb=$("qualityBody");qb.replaceChildren();
  const top=node("div",undefined,"qualityTop");
  top.append(node("div",q.total===null?"未形成完整质量分":q.total.toFixed(2)+" / 100","bigNumber"),node("span","我们新增的分析评分；不是 Buffett 原生评分","badge"));qb.append(top);
  if(q.status==="blocked_by_hard_risk")qb.append(node("div","严重风险阻断整体质量结论，算术平均不能消除风险。","alert"));
  qb.append(node("p","已观察贡献 "+q.observed_contribution.toFixed(2)+"；可能区间 "+q.possible_range.map(x=>x.toFixed(2)).join("–")+"；缺失项保留原权重。","muted"));
  for(const c of q.components){const row=node("div",undefined,"component");const label=node("div");label.append(node("strong",c.label),node("span"," 权重 "+c.weight+"%","muted"));row.append(label,progress(c.score===null?0:c.score,4),node("span",c.score===null?"缺口":c.score+" / 4","score"));qb.append(row);qb.append(detail(c.label+"：锚点、证据与反证",{score:c.score,reason:c.reason,judge:c.judge,judgment_type:c.judgment_type,anchors:c.anchors,anchor_reviews:c.anchor_reviews}));}
  qb.append(detail("预声明观察窗与未满足期间",q.observation_window));
  const vb=$("valuationBody");vb.replaceChildren();
  const tabs=node("div",undefined,"tabs");for(const name of ["bear","base","bull"]){const b=node("button",names[name],name===selectedScenario?"active":"");b.addEventListener("click",()=>{selectedScenario=name;render(current);});tabs.append(b);}vb.append(tabs);
  const s=r.valuation.scenarios.find(x=>x.name===selectedScenario)||r.valuation.scenarios[0];
  const grid=node("div",undefined,"metricGrid");grid.append(metric("企业价值 EV",s.ev===null?null:amount(s.ev,s.currency)),metric("股权价值（带符号）",s.equity===null?null:amount(s.equity,s.currency)),metric("模型币种 / 普通股",s.ordinary_value===null?null:amount(s.ordinary_value,s.currency," / 普通股")),metric("报价单位模型值",s.quote_value===null?null:amount(s.quote_value,r.security.quote_currency," / "+r.security.quote_unit)));vb.append(grid);
  vb.append(table(["同币种证券单位桥","模型值"],[["普通股",amount(s.ordinary_value,s.currency)], ["ADS / 报价单位",amount(s.quote_value_model_currency,s.currency)]]));
  vb.append(node("p","较输入报价的模型差额："+pct(s.upside_vs_price)+"；相对模型值差额："+pct(s.margin_to_model_value)+"。","muted"));
  if(s.comparison_status==="nonpositive_domain")vb.append(node("p","非正/困境模型结果仅保留带符号算术，不是可交易目标价；两个比较比率均不计算。","alert"));
  if(s.diagnostics.length){const list=node("div",undefined,"warning");s.diagnostics.forEach(d=>list.append(node("p",d.stage+" · "+d.code+"："+d.detail)));vb.append(list);}
  vb.append(detail("可重算：FCFF、折现日期、终值与EV→股权桥",s));vb.append(node("p","FCFF = EBIT×(1−税率)+D&A−Capex−Δ营运资本。条件模型值不构成入场价或交易指令。","footnote"));
  const cov=r.evidence_coverage, cb=$("coverageBody");cb.replaceChildren();const ct=node("div",undefined,"coverageTop");ct.append(node("strong",cov.satisfied+" / 27","bigNumber"),node("span","需求已声明满足","muted"));cb.append(ct,progress(cov.satisfied,27),node("p","支持性证据覆盖率 "+pct(cov.ratio)+"。不是准确率或信心；矛盾未解决不能算满足。","muted"));
  const groups=node("div",undefined,"moduleCounts");for(const [key,label]of[["quality","质量证据"],["dcf","DCF证据"],["comparison","报价比较"]])groups.append(metric(label,cov.modules[key].satisfied+" / "+cov.modules[key].declared));cb.append(groups);
  cb.append(node("p","另列文档可获取："+cov.document_availability.available+" / "+cov.document_availability.declared_fact_sources+" 个声明来源；不并入支持性覆盖率。","footnote"));
  cb.append(detail("27项冻结需求与未满足原因",cov.requirements));
  const ub=$("uncertaintyBody");ub.replaceChildren();
  const u=r.uncertainty;ub.append(metric("未解决矛盾",String(u.unresolved_contradictions.length)),metric("不合格事实",String(u.ineligible_facts.length)),node("p",u.hard_risks.length?"存在已声明的硬风险，须逐项复核。":"未声明硬风险；这不表示不存在风险。",u.hard_risks.length?"alert":"muted"));
  if(u.hard_risks.length)ub.append(detail("硬风险、证据与解除条件",u.hard_risks));
  if(u.unresolved_contradictions.length)ub.append(detail("未解决矛盾",u.unresolved_contradictions));
  if(u.ineligible_facts.length)ub.append(detail("时间、期间、缺失与来源问题",u.ineligible_facts));
  ub.append(detail(u.assumptions.length+" 项主观假设（不是事实）",u.assumptions),detail("预声明证伪条件（无自动监控）",u.falsifiers),detail("事实收据：期间、单位、发布时间与来源",r.evidence_receipt));
  for(const note of u.notes)ub.append(node("p",note,"footnote"));
  $("audit").textContent="结果 "+r.result_id.slice(0,16)+"… · 评估 "+r.evaluated_at+" · 独立结果缓存 "+cache.size+" 份";
}
function acceptResult(result) {
  validateResult(result);const previous=cache.get(result.result_id);
  if(previous&&canonical(previous)!==canonical(result))throw new Error("相同结果ID对应不同内容，拒绝覆盖");
  cache.set(result.result_id,result);render(result);$("message").textContent=previous?"已载入相同结果，未重复计数。":"结果已载入；来源文本不会执行。";
  return {duplicate:Boolean(previous),count:cache.size};
}
function loadDemo(id){try{acceptResult(parseStrict($(id).textContent));}catch(e){$("message").textContent=e.message;}}
$("completeButton").addEventListener("click",()=>loadDemo("completeDemo"));
$("historyButton").addEventListener("click",()=>loadDemo("historyDemo"));
$("fileInput").addEventListener("change",event=>{const file=event.target.files[0];if(!file)return;const reader=new FileReader();reader.onload=()=>{try{acceptResult(parseStrict(String(reader.result)));}catch(e){$("message").textContent="拒绝导入："+e.message;}};reader.onerror=()=>{$("message").textContent="无法读取本地文件";};reader.readAsText(file,"utf-8");});
window.dashboardAPI={parseStrict,validateSchema,validateResult,acceptResult,canonical,render};
loadDemo(location.hash==="#history"?"historyDemo":location.hash==="#risk"?"riskDemo":"completeDemo");
