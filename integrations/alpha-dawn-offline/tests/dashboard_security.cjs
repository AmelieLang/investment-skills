"use strict";
const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict"),path=require("node:path");
const root=path.resolve(__dirname,"..");
const complete=JSON.parse(fs.readFileSync(path.join(root,"examples/synthetic-complete.result.json"),"utf8"));
const history=JSON.parse(fs.readFileSync(path.join(root,"examples/apple-fy2023-public-gaps.result.json"),"utf8"));
const hardRisk=JSON.parse(fs.readFileSync(path.join(root,"examples/synthetic-hard-risk.result.json"),"utf8"));
const all=[];
class Element {
  constructor(tag){this.tag=tag;this.children=[];this._text="";this.handlers={};all.push(this);}
  set textContent(v){this._text=String(v);this.children=[];}
  get textContent(){return this._text+this.children.map(x=>x.textContent).join("");}
  set innerHTML(v){throw new Error("innerHTML is forbidden");}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this._text="";this.children=[...nodes];}
  addEventListener(name,handler){this.handlers[name]=handler;}
}
const ids=new Map();
const document={getElementById(id){if(!ids.has(id))ids.set(id,new Element("div"));return ids.get(id);},createElement(tag){return new Element(tag);}};
document.getElementById("completeDemo").textContent=JSON.stringify(complete);
document.getElementById("historyDemo").textContent=JSON.stringify(history);
document.getElementById("riskDemo").textContent=JSON.stringify(hardRisk);
document.getElementById("resultSchema").textContent=fs.readFileSync(path.join(root,"schema/result.v1.json"),"utf8");
document.getElementById("requirementsContract").textContent=fs.readFileSync(path.join(root,"config/requirements.v1.json"),"utf8");
let networkCalls=0;
const forbidden=()=>{networkCalls++;throw new Error("network forbidden");};
const window={};
const sandbox={document,window,location:{hash:""},TextEncoder,Intl,console,fetch:forbidden,WebSocket:forbidden,XMLHttpRequest:forbidden,navigator:{sendBeacon:forbidden},FileReader:class{}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(root,"ui/dashboard.js"),"utf8"),sandbox);
const api=window.dashboardAPI,checks=[];
function test(name,fn){fn();checks.push({name,status:"passed"});}
test("default four panels render",()=>{for(const id of ["qualityBody","valuationBody","coverageBody","uncertaintyBody"])assert.ok(document.getElementById(id).children.length);});
test("duplicate results never double count",()=>{const x=api.acceptResult(complete);assert.equal(x.duplicate,true);assert.equal(x.count,1);});
test("same ID different payload rejected",()=>{const x=structuredClone(complete);x.uncertainty.notes.push('Different audit note with same ID');assert.throws(()=>api.acceptResult(x),/相同结果ID/);});
test("malicious source and native text remain text",()=>{const x=structuredClone(complete),payload='</script><img src="https://invalid.example" onerror="pwned=1">';x.result_id="a".repeat(64);x.native_output.note=payload;x.evidence_receipt[0].value=payload;api.acceptResult(x);assert.ok(all.some(e=>e.textContent.includes('</script><img')));assert.equal(all.filter(e=>e.tag==='img').length,0);assert.equal(sandbox.pwned,undefined);});
test("malformed result refused",()=>assert.throws(()=>api.acceptResult({}),/必需字段/));
test("nonfinite nested output refused",()=>{const x=structuredClone(complete);x.quality.total=Infinity;assert.throws(()=>api.validateResult(x),/非有限/);});
test("forged finite totals and coverage refused",()=>{const x=structuredClone(complete);x.quality.total=99;assert.throws(()=>api.validateResult(x),/总分/);const y=structuredClone(complete);y.evidence_coverage.ratio=.7;assert.throws(()=>api.validateResult(y),/覆盖/);});
test("duplicate JSON keys refused",()=>assert.throws(()=>api.parseStrict('{"x":1,"x":2}'),/重复/));
test("prototype-shaped data remains inert",()=>{const x=api.parseStrict('{"__proto__":{"polluted":1}}');assert.equal({}.polluted,undefined);assert.equal(x.__proto__.polluted,1);});
test("nonfinite number token refused",()=>assert.throws(()=>api.parseStrict('{"x":1e309}'),/非有限/));
test("historical gaps render without synthetic facts",()=>{api.acceptResult(history);assert.match(document.getElementById("qualityBody").textContent,/未形成完整/);assert.equal(history.security.listing_id,"NASDAQ:AAPL");});
test("send/trade enabled payload refused",()=>{const x=structuredClone(complete);x.capabilities.send=true;assert.throws(()=>api.validateResult(x),/常量|发送/);});
test("R1 forged confirmed default cannot keep 75",()=>{const x=structuredClone(complete);const flag=structuredClone(hardRisk.quality.hard_risks[0]);x.quality.hard_risks=[flag];x.uncertainty.hard_risks=[flag];assert.throws(()=>api.validateResult(x),/硬风险/);});
test("R1 evidence receipt is required",()=>{const x=structuredClone(complete);delete x.evidence_receipt;assert.throws(()=>api.validateResult(x),/必需字段/);});
test("R1 malformed nested native and valuation records refused",()=>{const x=structuredClone(complete);x.native_output.status=[];assert.throws(()=>api.validateResult(x),/类型/);const y=structuredClone(complete);delete y.valuation.scenarios[0].bridge;assert.throws(()=>api.validateResult(y),/必需字段/);});
test("R1 frozen requirement IDs and groups enforced",()=>{const x=structuredClone(complete);x.evidence_coverage.requirements[0].id="Q99";assert.throws(()=>api.validateResult(x),/需求/);const y=structuredClone(complete);y.evidence_coverage.modules.quality.satisfied=0;assert.throws(()=>api.validateResult(y),/计数/);});
test("R1 negative and zero model ratios refused",()=>{for(const v of [-13.6,0]){const x=structuredClone(complete);x.valuation.scenarios[0].quote_value=v;assert.throws(()=>api.validateResult(x),/非正/);}});
test("R1 material risk view suppresses main score",()=>{api.acceptResult(hardRisk);assert.match(document.getElementById("qualityBody").textContent,/严重风险阻断/);assert.doesNotMatch(document.getElementById("qualityBody").textContent,/75.00 \/ 100/);});
test("network calls remain zero",()=>assert.equal(networkCalls,0));
const html=fs.readFileSync(path.join(root,"dashboard.html"),"utf8");
test("CSP blocks connection and form routes",()=>{assert.match(html,/connect-src 'none'/);assert.match(html,/form-action 'none'/);assert.doesNotMatch(html,/<script[^>]+src=/);assert.doesNotMatch(html,/<link[^>]+href=/);});
test("embedded JSON is escaped",()=>{for(const id of ["completeDemo","historyDemo"]){const body=html.match(new RegExp('<script type="application/json" id="'+id+'">([\\s\\S]*?)</script>'))[1];assert.doesNotMatch(body,/[<>]/);JSON.parse(body);}});
fs.mkdirSync(path.join(root,"qa"),{recursive:true});
fs.writeFileSync(path.join(root,"qa/dashboard-tests.json"),JSON.stringify({suite:"dashboard offline security",passed:checks.length,failed:0,networkCalls,checks},null,2));
process.stdout.write(JSON.stringify({passed:checks.length,failed:0,networkCalls})+"\n");
