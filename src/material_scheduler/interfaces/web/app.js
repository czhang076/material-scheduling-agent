"use strict";

const $ = id => document.getElementById(id);
const labels = {PASS:"规则通过",NEEDS_INPUT:"资料不足",BLOCKED:"已阻断",NEEDS_REVIEW:"需人工核对",SOURCE_CONFLICT:"来源冲突",READY:"草稿就绪",PENDING_CONFIRMATION:"待确认",STALE:"已过期",READY_DRAFTS:"草稿已就绪",NEEDS_CONFIRMATION:"等待你的确认",PARTIAL:"部分完成",FAILED:"执行未完成",INCOMPLETE:"尚未完成",QUEUED:"等待开始",RUNNING:"执行中",FINISHED:"已结束",INTERRUPTED:"运行已中断"};
const fieldNames = {title:"标题",copy_text:"文案",rights_status:"版权状态",supported_channels:"支持渠道",material:"素材资料",tags:"标签",description:"描述"};
const toolNames = {read_material:"读取素材",lookup_metadata:"补查资料",check_rules:"检查规则",query_slots:"查询时段",save_draft:"保存草稿",finish:"结束决策"};
const channels = {douyin:"抖音",xiaohongshu:"小红书"};
const messages = {INVALID_INPUT:"请求格式或时间范围有误，请检查输入。",REQUEST_ID_CONFLICT:"同一任务编号对应的要求已改变，请新建任务。",RUN_BUSY:"已有任务正在执行，请等待它完成。",RUN_MODE_CONFLICT:"此提交已使用另一种模式，请查询原运行。",CONFIRMATION_INCOMPLETE:"请逐项接受当前方案的全部待确认事项。",DRAFT_VERSION_CONFLICT:"草稿版本已变化，本次确认未应用。",STALE_DRAFT:"这份方案已失效，请重新核验并规划。",STALE_REVIEW:"审核资料已变化，旧版本不能继续确认，请重新规划。",SLOT_CONFLICT:"候选时段已出现新占用，请重新规划。",MODEL_CONFIGURATION_ERROR:"真实模型尚未配置，可先使用离线演示。",SESSION_EXPIRED:"本地会话已更新，请重新连接。",CSRF_REJECTED:"本地会话已更新，请重新连接。",RUN_NOT_FOUND:"未查到这次提交，请使用原要求重试。",SAVE_FAILED:"草稿保存失败，已保留此前的成功步骤。",SAVE_OUTCOME_UNKNOWN:"保存回执未知，请先查询账本或复用原任务重试。",TRACE_UNAVAILABLE:"执行记录不完整，请核对账本中的实际草稿。",MODEL_AUTH_ERROR:"模型服务鉴权失败，请核对服务端配置。",MODEL_TIMEOUT:"模型响应超时，已保留实际保存结果。",TOOL_UNAVAILABLE:"工具暂时不可用。",ITEM_LIMIT_REACHED:"该项已到执行上限。",RETRY_LIMIT_REACHED:"已达到相同操作的重试上限。"};
const state = {csrf:null,catalog:null,drafts:[],runs:[],selected:new Set(["M01"]),job:null,events:[],cursor:0,view:"materials",filter:"all",connected:false,failures:0,timer:null,submitting:false,pending:null,formId:newId("REQ-WEB"),signature:null,confirmation:null,booted:false,loadEpoch:0};

function newId(prefix){return prefix+"-"+crypto.randomUUID().replaceAll("-","");}
function rememberSubmission(value){try{if(value)localStorage.setItem("yingshu-pending-submission",value);else localStorage.removeItem("yingshu-pending-submission");}catch{}}
function renderPending(){
  const pending=state.pending;show("pending-submission",!!pending);if(!pending)return;
  let request=pending.request;try{if(typeof request==="string")request=JSON.parse(request);}catch{request=null;}
  const times=(request?.items||[]).slice(0,3).map(item=>stamp(item.time_requirement?.requested_start)).join("、");
  text("pending-summary",(request?.request_id||"原始 JSON 请求")+" · "+(pending.mode==="real"?"真实模型 · 重试会产生 API 用量":"离线 Mock")+(times?" · "+times:"")+"。当前编辑不会替换这笔原提交。");
  $("pending-query").disabled=state.submitting;$("pending-retry").disabled=state.submitting;
}
async function retryPendingSubmission(){if(state.pending)await submitRequest(state.pending.request,state.pending.mode);}
function el(tag,cls,text){const node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined&&text!==null)node.textContent=String(text);return node;}
function text(id,value){$(id).textContent=value;}
function show(id,visible=true){$(id).classList.toggle("hidden",!visible);}
function tone(status){return ["PASS","READY","READY_DRAFTS"].includes(status)?"green":["NEEDS_INPUT","NEEDS_REVIEW","SOURCE_CONFLICT","PENDING_CONFIRMATION","NEEDS_CONFIRMATION","PARTIAL"].includes(status)?"amber":["BLOCKED","FAILED","STALE","INTERRUPTED"].includes(status)?"red":"neutral";}
function badge(status,override){return el("span","badge "+tone(status),override||labels[status]||status);}
function friendly(code){return messages[code]||"操作未完成，请核对实际状态后再试。";}
function stamp(value){if(!value)return "—";const match=String(value).match(/(Z|[+-]\d\d:\d\d)$/);return value.slice(0,10)+" "+value.slice(11,16)+" · UTC"+(match?(match[1]==="Z"?"+00:00":match[1]):"");}
function timeBlock(value){const node=el("div");node.append(el("div","time-main",value?value.slice(5,10).replace("-",".")+" "+value.slice(11,16):"—"));if(value){const m=value.match(/(Z|[+-]\d\d:\d\d)$/);node.append(el("div","cell-sub",value.slice(0,4)+" · UTC"+(m?(m[1]==="Z"?"+00:00":m[1]):"")));node.title=stamp(value);}return node;}
function toast(message,error=false){text("toast",message);$("toast").classList.toggle("error",error);show("toast");clearTimeout(toast.timer);toast.timer=setTimeout(()=>show("toast",false),4200);}
function network(connected){state.connected=connected;show("network-banner",!connected);text("connection-label",connected?"本地连接正常":"连接中断，待查询");$("connection-dot").style.background=connected?"#aac98f":"#bc8a6b";}

async function api(path,{method="GET",body,raw=false}={}){
  const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),12000);
  try{
    const headers={};if(body!==undefined){headers["Content-Type"]="application/json";headers["X-CSRF-Token"]=state.csrf||"";}
    const response=await fetch(path,{method,credentials:"same-origin",headers,body:body===undefined?undefined:JSON.stringify(body),signal:controller.signal,cache:"no-store"});
    const data=raw?await response.text():await response.json();
    if(!response.ok){const error=new Error(friendly(data.error?.code));error.code=data.error?.code;error.status=response.status;throw error;}
    return data;
  }catch(error){if(!error.status){error.network=true;network(false);}throw error;}finally{clearTimeout(timeout);}
}

function businessRequest(){
  const offset=$("timezone").value;const date=$("target-date").value;const time=$("target-time").value;
  const timestamp=value=>value+(value.length===16?":00":"")+offset;
  const requirement={requested_start:date+"T"+time+":00"+offset,duration_minutes:Number($("duration").value),mode:$("time-mode").value};
  if($("allow-window").checked)requirement.alternative_window={start:timestamp($("window-start").value),end:timestamp($("window-end").value)};
  const ordered=(state.catalog?.materials||[]).map(row=>row.material.material_id).filter(id=>state.selected.has(id));
  return {schema_version:"1.0",items:ordered.map((id,index)=>({item_id:"I"+String(index+1).padStart(2,"0"),material_id:id,channel:$("channel").value,time_requirement:structuredClone(requirement)}))};
}
function updatePreview(){text("request-id",state.formId);if(!$("json-mode").checked)$("json-input").value=JSON.stringify({...businessRequest(),request_id:state.formId},null,2);text("selection-count",$("json-mode").checked?"使用 JSON 请求":"已选 "+state.selected.size+" 项");}
function requestForSubmit(){if($("json-mode").checked)return $("json-input").value;const payload=businessRequest();if(!payload.items.length)throw new Error("请至少选择一项素材。");const signature=JSON.stringify(payload);if(state.signature!==null&&state.signature!==signature)state.formId=newId("REQ-WEB");state.signature=signature;updatePreview();return {...payload,request_id:state.formId};}

async function bootstrap(){
  const data=await api("/api/bootstrap?channel="+encodeURIComponent($("channel").value));
  state.csrf=data.csrf_token;state.catalog=data.catalog;state.drafts=data.drafts;state.runs=data.runs;state.failures=0;network(true);
  const option=$("model-mode").querySelector('[value="real"]');option.disabled=!data.real_model.available;option.textContent=data.real_model.available?data.real_model.name+" · 真实模型":"真实模型 · 尚未配置";
  if(!data.real_model.available&&$("model-mode").value==="real")$("model-mode").value="mock";
  if(!state.booted){
    const first=state.catalog.slot_offers[0]?.start;if(first){$("target-date").value=first.slice(0,10);$("target-time").value=first.slice(11,16);$("window-start").value=first.slice(0,16);$("window-end").value=first.slice(0,10)+"T21:00";}
    if(!state.catalog.materials.some(row=>state.selected.has(row.material.material_id))){state.selected=new Set(state.catalog.materials.slice(0,1).map(row=>row.material.material_id));}
    state.booted=true;
  }
  modeHint();updatePreview();render();text("sync-time","最近同步 "+new Date().toLocaleTimeString("zh-CN",{hour12:false}));
}
function modeHint(){text("mode-hint",$("model-mode").value==="real"?"将调用服务端配置的真实模型，并产生 API 用量。":"规则 Mock 用于验证流程，不证明真实模型效果。");}
function jobItems(){return state.job?.current?.items||[];}
function outcome(itemId){return state.job?.result?.items?.find(item=>item.item_id===itemId);}
function toolEvents(){return state.events.filter(envelope=>envelope.event.type==="tool_observation").map(envelope=>envelope.event);}
function latestSave(itemId){const attempt=outcome(itemId)?.save_attempt;if(attempt&&attempt.save_status!=="NOT_ATTEMPTED")return attempt;const entry=toolEvents().filter(event=>event.action.tool==="save_draft"&&event.observation.item_id===itemId).at(-1);return entry?(entry.observation.ok?{save_status:entry.observation.data.save_status}:{save_status:entry.observation.error.code==="SAVE_OUTCOME_UNKNOWN"?"UNKNOWN":"FAILED"}):null;}
function materialRows(){
  const materials=state.catalog?.materials||[];const input=state.job?.request?.items||[];
  const rows=input.map(ri=>{const base=materials.find(row=>row.material.material_id===ri.material_id)||{material:{material_id:ri.material_id,title:"未找到素材",revision:null,source_id:null},review_preview:{review_status:"NEEDS_INPUT",missing_fields:["material"],findings:[]}};const current=jobItems().find(item=>item.item_id===ri.item_id);return {...base,ri,current,review_preview:current?.review||base.review_preview};});
  const included=new Set(input.map(item=>item.material_id));return [...rows,...materials.filter(row=>!included.has(row.material.material_id))];
}

function render(){
  const materials=state.catalog?.materials||[];text("stat-materials",materials.length);text("nav-material-count",materials.length);text("nav-draft-count",state.drafts.length);text("stat-ready",state.drafts.filter(draft=>draft.draft_state==="READY").length);text("stat-pending",state.drafts.filter(draft=>draft.draft_state==="PENDING_CONFIRMATION").length);
  text("stat-tools",state.job?(state.job.result?.stats?.tool_dispatches??toolEvents().filter(event=>event.dispatched).length):"—");text("stat-tools-caption",state.job?"实际派发 · 尝试数见执行记录":"运行后展示实际记录");
  text("rule-version",state.catalog?"规则 "+state.catalog.rule_set_version:"规则加载中");renderMaterials();renderDrafts();renderHistory();renderRun();
}
function renderMaterials(){
  let rows=materialRows();if(state.filter==="current")rows=rows.filter(row=>row.ri);if(state.filter==="attention")rows=rows.filter(row=>row.review_preview.review_status!=="PASS"||["PENDING_CONFIRMATION","STALE"].includes(row.current?.draft?.draft_state)||["FAILED","UNKNOWN"].includes(latestSave(row.ri?.item_id)?.save_status));
  const body=$("material-rows");body.replaceChildren();text("queue-count",rows.length);
  if(!rows.length){const td=el("td","empty-table",state.filter==="current"?"尚无运行中的任务。":"当前筛选下没有素材。");td.colSpan=6;body.append(el("tr"));body.lastChild.append(td);}
  for(const row of rows){
    const material=row.material;const draft=row.current?.draft;const attempt=latestSave(row.ri?.item_id);const tr=el("tr");tr.dataset.materialId=material.material_id;if(row.ri)tr.dataset.itemId=row.ri.item_id;
    const checkCell=el("td","check-cell");const check=el("input");check.type="checkbox";check.checked=state.selected.has(material.material_id);check.disabled=$("json-mode").checked;check.setAttribute("aria-label","选择 "+material.material_id+" "+(material.title||"素材"));check.addEventListener("change",()=>{check.checked?state.selected.add(material.material_id):state.selected.delete(material.material_id);updatePreview();renderMaterials();});checkCell.append(check);
    const name=el("td","material-name");const titleLine=el("div","material-title-line");titleLine.append(el("span","material-glyph","▹"));const info=el("div");info.append(el("strong",null,material.title||"未提供标题"),el("div","material-id",material.material_id+(row.ri?" · "+row.ri.item_id:"")+" · "+(channels[row.ri?.channel||$("channel").value]||row.ri?.channel||$("channel").value)));titleLine.append(info);name.append(titleLine);
    const review=el("td");review.append(badge(row.review_preview.review_status));const missing=row.review_preview.missing_fields||[];if(missing.length)review.append(el("div","cell-sub","缺"+missing.map(field=>fieldNames[field]||field).join("、")));
    const result=el("td");
    if(attempt?.save_status==="FAILED"||attempt?.save_status==="UNKNOWN"){result.append(badge(attempt.save_status==="FAILED"?"FAILED":"NEEDS_CONFIRMATION",attempt.save_status==="FAILED"?"本次保存失败":"保存回执未知"));if(draft)result.append(el("div","cell-sub","账本仍有"+(labels[draft.draft_state]||draft.draft_state)));}
    else if(draft){result.append(badge(draft.draft_state));result.append(el("div","cell-sub",attempt?.save_status==="REUSED"?"已复用 · 版本 "+draft.version:"已保存 · 版本 "+draft.version));}
    else if(row.ri){const final=outcome(row.ri.item_id);result.append(el("span","muted small",final?(labels[final.status]||"未形成草稿"):"等待处理"));}
    else result.append(el("span","muted small","本次未处理"));
    const time=el("td");time.append(timeBlock(draft?.candidate.start));const actions=el("td","align-right");const button=el("button","row-action"+(draft?.draft_state==="PENDING_CONFIRMATION"?" strong":""),draft?.draft_state==="PENDING_CONFIRMATION"?"查看并确认":"查看详情");button.addEventListener("click",()=>draft?.draft_state==="PENDING_CONFIRMATION"?openConfirmation(draft.draft_id):openDetail(row));actions.append(button);tr.append(checkCell,name,review,result,time,actions);body.append(tr);
  }
  $("select-all").disabled=$("json-mode").checked||!rows.length;$("select-all").checked=rows.length>0&&rows.every(row=>state.selected.has(row.material.material_id));$("select-all").indeterminate=rows.some(row=>state.selected.has(row.material.material_id))&&!$("select-all").checked;
}
function renderDrafts(){const target=$("draft-list");target.replaceChildren();if(!state.drafts.length){target.append(empty("尚无排期草稿","选择素材并运行后，已保存的草稿会出现在这里。"));return;}for(const draft of state.drafts){const card=el("article","draft-card");const top=el("div","draft-top");const source=state.catalog?.materials.find(row=>row.material.material_id===draft.material_id)?.material;top.append(el("strong",null,source?.title||draft.material_id),badge(draft.draft_state));const time=el("div","draft-time");time.append(el("small","muted small","原始要求"),timeBlock(draft.requested_start),el("div","arrow","↓"),el("small","muted small","当前候选"),timeBlock(draft.candidate.start));card.append(top,time,el("div","draft-meta",draft.material_id+" · "+(channels[draft.channel]||draft.channel)+" · 版本 "+draft.version),el("div","draft-meta",draft.draft_id),el("div","draft-meta","最近核验："+stamp(draft.last_validated_at)));if(draft.draft_state==="PENDING_CONFIRMATION"){const button=el("button","button secondary compact","查看并确认");button.addEventListener("click",()=>openConfirmation(draft.draft_id));card.append(button);}else if(draft.draft_state==="STALE"){const button=el("button","button secondary compact","重新核验");button.addEventListener("click",()=>revalidate(draft.request_id));card.append(button);}target.append(card);}}
function renderHistory(){const target=$("run-history");target.replaceChildren();if(!state.runs.length){target.append(empty("尚无运行记录","每次实际执行都会保留独立编号。"));return;}for(const run of state.runs){const row=el("button","history-row");const info=el("div");info.append(el("strong",null,run.request_id),el("small","mono",run.run_id),el("small",null,stamp(run.created_at)));row.append(info,badge(run.status,(run.mode==="mock"?"Mock · ":"真实接口 · ")+(labels[run.status]||run.status)));row.addEventListener("click",()=>loadRun(run.run_id,true).catch(handleReadError));target.append(row);}}
function empty(title,description){const node=el("div","empty-state");node.append(el("span","empty-icon","↳"));const words=el("div");words.append(el("strong",null,title),el("p",null,description));node.append(words);return node;}
function renderRun(){
  const job=state.job;const target=$("timeline");target.replaceChildren();
  if(!job){text("run-mode-badge","尚未运行");$("run-mode-badge").className="badge neutral";text("run-caption","选择素材并开始，实际动作与工具返回会在这里出现。");target.append(empty("等待第一份实际记录","这里展示公开动作与结果，不展示模型内部思考。"));for(const id of ["run-status","retry-run","download-trace","revalidate"])show(id,false);return;}
  const active=["QUEUED","RUNNING"].includes(job.status);text("run-mode-badge",job.mode==="mock"?"离线演示 · Mock":"真实接口 · "+(job.result?.model?.name||"模型"));$("run-mode-badge").className="badge "+(job.mode==="mock"?"amber":"green");text("run-caption",job.request_id+" · "+job.run_id);
  const banner=$("run-status");banner.replaceChildren();show("run-status");banner.className="run-status";let summary="";let kind="";
  if(active){banner.append(el("span","running-dot"));summary=toolEvents().length?"正在根据实际工具结果继续处理…":"任务已接收，等待第一个动作…";}
  else if(job.status==="INTERRUPTED"){summary=job.error?.code==="RUN_STATE_UNPERSISTED"?"本次运行已结束，但运行状态尚未可靠保存。草稿事实仍保留；存储恢复后，复用原提交可完成对账。":"服务已重启，本次运行中断。草稿事实仍保留，请核验后复用原任务重试。";kind="amber";}
  else if(job.error){summary=friendly(job.error.code);kind="red";}
  else {const result=job.result;const current=jobItems();const failed=result?.items?.some(item=>["FAILED","UNKNOWN"].includes(item.save_attempt?.save_status));if(failed){const unknown=result.items.some(item=>item.save_attempt?.save_status==="UNKNOWN");summary=unknown?"本次保存回执未知。账本中已有的草稿不代表本次保存已确认成功。":"本次保存未完成，已保留真实审核结果和此前保存的草稿。";kind=unknown?"amber":"red";}
    else if(result?.execution_status==="FAILED"||result?.trace_complete===false){summary="本次执行或证据记录未完整完成。请核对停止原因与账本中的真实草稿。";kind="red";}
    else if(current.length&&current.every(item=>item.draft?.draft_state==="READY")){summary="当前草稿已就绪。已满足审核与确认要求，仍仅保存在本地。";}
    else if(current.some(item=>item.draft?.draft_state==="STALE")){summary="账本中的方案已过期，请重新核验并规划。";kind="amber";}
    else if(result){summary=(labels[result.task_status]||result.task_status)+(result.task_status==="NEEDS_CONFIRMATION"?"：建议已保存，硬性时间调整仍需你的同意。":"。请查看逐项结果与实际执行记录。");kind=tone(result.task_status)==="red"?"red":tone(result.task_status)==="amber"?"amber":"";if(result.trace_complete===false){summary+=" 执行证据不完整，请核对实际账本。";kind="red";}}
    else{summary="本次运行尚无完整结果，请查询当前账本。";kind="amber";}}
  banner.append(el("span",null,summary));if(kind)banner.classList.add(kind);show("retry-run",!active);text("retry-run",job.mode==="real"?"使用真实模型重试":"复用任务重试");show("revalidate",!active);show("download-trace",!active&&state.events.length>0);
  const steps=toolEvents();if(!steps.length){target.append(empty(active?"正在等待提供者返回动作":"暂无工具派发记录",active?"关闭或刷新页面不会取消这个后台任务。":"可查看停止原因，或重新核验账本。"));}
  for(const [index,event] of steps.entries()){const observation=event.observation;const item=job.request.items.find(item=>item.item_id===observation.item_id);const row=el("div","timeline-row");row.dataset.tool=event.action.tool;row.dataset.ok=String(observation.ok);row.append(el("span","step-mark"+(observation.ok?"":" error"),observation.ok?"✓":"!"));const title=el("div","step-title");title.append(el("strong",null,toolNames[event.action.tool]||event.action.tool),el("span",null,item?item.material_id+" · "+item.item_id:"整个任务"),el("span","mono","STEP "+String(index+1).padStart(2,"0")));row.append(title,el("div","step-reason",event.action.arguments.rationale||"未提供公开理由"),el("div","step-result"+(observation.ok?"":" error"),summarize(event)));
    const detail=el("details","step-details");detail.append(el("summary",null,"查看实际参数与返回"),el("pre",null,JSON.stringify({call_id:event.call_id,parameters:event.action.arguments,observation},null,2)));row.append(detail);target.append(row);}
}
function summarize(event){const observation=event.observation;if(!observation.ok)return friendly(observation.error.code)+"（"+observation.error.code+"）";const data=observation.data;switch(event.action.tool){case "read_material":return data.material?"已读取素材版本 "+data.revision+(data.missing_fields.length?"，仍缺"+data.missing_fields.map(key=>fieldNames[key]||key).join("、"):"，必要元数据齐全。"):"目录中未找到这份素材。";case "lookup_metadata":return data.applied_fields.length?"已补齐"+data.applied_fields.map(key=>fieldNames[key]||key).join("、"):"补查未补齐所需资料，缺口继续保留。";case "check_rules":return (labels[data.review_status]||data.review_status)+" · "+data.findings.length+" 条规则发现";case "query_slots":return data.candidates.length?"已返回 "+data.candidates.length+" 个候选，首个为 "+stamp(data.candidates[0].start):"本次查询没有可用候选。";case "save_draft":return (data.save_status==="REUSED"?"复用已有草稿":"草稿已保存")+" · "+(labels[data.draft_state]||data.draft_state)+" · 版本 "+data.version;default:return "已结束选择，最终状态以工具与账本为准。";}}
function findingNode(finding){const box=el("div","finding");box.append(el("p",null,finding.message));if(typeof finding.value==="string"&&Number.isInteger(finding.start)&&Number.isInteger(finding.end)){const points=Array.from(finding.value);const line=el("div","evidence-line");line.append(document.createTextNode(points.slice(0,finding.start).join("")),el("mark",null,points.slice(finding.start,finding.end).join("")),document.createTextNode(points.slice(finding.end).join("")));box.append(line);}else box.append(el("div","evidence-line",Array.isArray(finding.value)?finding.value.join("、"):finding.value??"未提供该字段"));box.append(el("small",null,"规则 "+finding.rule_id+" · 来源 "+finding.source_id+" · 版本 "+finding.material_revision+" · "+(fieldNames[finding.field]||finding.field)));return box;}
function openDetail(row){text("detail-title",row.material.title||"未找到素材");const target=$("detail-body");target.replaceChildren();target.append(el("p","metadata-line",row.material.material_id+" · 来源 "+(row.material.source_id||"未提供")+" · 版本 "+(row.material.revision??"未知")),badge(row.review_preview.review_status),el("h3",null,"待发布文案"),el("div","source-text",row.material.copy_text||"尚无文案资料"));const missing=row.review_preview.missing_fields||[];if(missing.length)target.append(el("h3",null,"资料缺口"),el("p",null,missing.map(key=>fieldNames[key]||key).join("、")));target.append(el("h3",null,"规则与原文依据"));if(!row.review_preview.findings?.length)target.append(el("p",null,"当前规则预览未发现风险；不包含图片或视频画面审核。"));for(const finding of row.review_preview.findings||[])target.append(findingNode(finding));if(row.source_conflicts?.length)target.append(el("p",null,"来源存在矛盾，需核对后才能继续。"));$("detail-dialog").showModal();}

async function openConfirmation(draftId){
  try{const draft=await api("/api/drafts/"+encodeURIComponent(draftId));if(draft.draft_state!=="PENDING_CONFIRMATION"){toast("这份草稿已不在待确认状态，请查看当前账本。",true);await refreshFacts();return;}
    state.confirmation={draft,operation:newId("CONF-WEB"),submitting:false,invalid:false,locked:false};text("confirm-title","确认这份排期建议");const target=$("confirm-body");target.replaceChildren();target.append(el("p","metadata-line",draft.draft_id+" · 当前版本 "+draft.version));const comparison=el("div","time-comparison");const original=el("div");original.append(el("small",null,"原始要求"),timeBlock(draft.requested_start));const proposed=el("div");proposed.append(el("small",null,"当前建议"),timeBlock(draft.candidate.start));comparison.append(original,el("span","change-arrow","→"),proposed);target.append(comparison,el("h3",null,"请逐项确认"));
    for(const [index,key] of draft.pending_confirmations.entries()){const section=el("div","confirmation-item");const label=el("label","check-label");const checkbox=el("input");checkbox.type="checkbox";checkbox.dataset.confirmation=key;checkbox.id="accept-"+index;let explanation=key==="TIME_CHANGE"?"我接受以上发布时间调整":key==="TIME_RANGE_UNSPECIFIED"?"我接受当前建议对应的替代范围":"我已核对并接受此人工审核风险";label.append(checkbox,el("span",null,explanation));checkbox.addEventListener("change",updateConfirmation);section.append(label,el("small","mono",key));target.append(section);if(key.startsWith("RISK:")){for(const finding of draft.findings.filter(finding=>"RISK:"+finding.rule_id===key))target.append(findingNode(finding));}}
    target.append(el("h3",null,"确认说明（选填）"));const note=el("textarea","confirmation-note");note.id="confirmation-note";note.rows=2;note.maxLength=1000;note.setAttribute("aria-label","确认说明");target.append(note);const error=el("div","form-error hidden");error.id="confirmation-error";error.setAttribute("role","alert");target.append(error);text("confirm-submit","确认当前版本");updateConfirmation();$("confirm-dialog").showModal();
  }catch(error){toast(error.message,true);}
}
function updateConfirmation(){const current=state.confirmation;const checks=Array.from($("confirm-body").querySelectorAll("input[data-confirmation]"));$("confirm-submit").disabled=!current||current.submitting||current.invalid||!checks.length||!checks.every(input=>input.checked);}
async function confirmDraft(){const current=state.confirmation;if(!current||$("confirm-submit").disabled)return;current.submitting=true;current.locked=true;for(const input of $("confirm-body").querySelectorAll("input,textarea"))input.disabled=true;updateConfirmation();text("confirm-submit","正在确认…");try{const draft=await api("/api/drafts/"+encodeURIComponent(current.draft.draft_id)+"/confirm",{method:"POST",body:{confirmation_id:current.operation,expected_version:current.draft.version,accepted_item_ids:[...current.draft.pending_confirmations],actor:"local-user",note:$("confirmation-note").value||null}});if(draft.draft_state!=="READY")throw new Error("请核对服务端返回的当前状态。");$("confirm-dialog").close();toast("当前版本已确认，草稿已就绪。仍未发布。");await refreshFacts();}catch(error){current.submitting=false;if(!error.network)current.invalid=true;text("confirm-submit",error.network?"查询后重试同一确认":"请关闭并重新查看方案");text("confirmation-error",error.network?"连接中断，确认结果待查询。重试将复用同一操作编号，不会重复确认。":error.message+" 请关闭面板，重新核验后查看最新版本。");show("confirmation-error");updateConfirmation();if(error.status)await refreshFacts().catch(()=>{});}}

async function refreshFacts(){await bootstrap();if(state.job)await loadRun(state.job.run_id,false);}
async function revalidate(requestId){try{await api("/api/requests/"+encodeURIComponent(requestId)+"/revalidate",{method:"POST",body:{}});toast("已按当前资料和占用重新核验。");await refreshFacts();}catch(error){toast(error.message,true);}}
async function loadRun(runId,scroll){
  const epoch=state.loadEpoch=(state.loadEpoch||0)+1;clearTimeout(state.timer);
  const same=state.job?.run_id===runId;let cursor=same?state.cursor:0;const events=new Map((same?state.events:[]).map(event=>[event.sequence,event]));
  try{
    const job=await api("/api/runs/"+encodeURIComponent(runId));if(epoch!==state.loadEpoch)return;
    for(let page=0;page<15;page++){
      const data=await api("/api/runs/"+encodeURIComponent(runId)+"/events?after="+cursor+"&limit=100");if(epoch!==state.loadEpoch)return;
      for(const event of data.events){if(event.run_id!==runId)throw new Error("执行记录编号与当前任务不一致，请重新查询。");events.set(event.sequence,event);}
      cursor=data.next_after;if(!data.has_more)break;
    }
    state.job=job;state.events=[...events.values()].sort((a,b)=>a.sequence-b.sequence);state.cursor=cursor;
    try{localStorage.setItem("yingshu-last-run",runId);}catch{}
    state.failures=0;network(true);render();if(scroll)$("execution-card").scrollIntoView({behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"instant":"smooth",block:"start"});
    if(["QUEUED","RUNNING"].includes(job.status))state.timer=setTimeout(poll,800);
    else{const data=await api("/api/bootstrap?channel="+encodeURIComponent($("channel").value));if(epoch!==state.loadEpoch)return;state.csrf=data.csrf_token;state.runs=data.runs;state.drafts=data.drafts;state.catalog=data.catalog;render();}
  }catch(error){if(epoch===state.loadEpoch)throw error;}
}
async function poll(){try{if(!document.hidden&&state.job)await loadRun(state.job.run_id,false);else if(state.job&&["QUEUED","RUNNING"].includes(state.job.status))state.timer=setTimeout(poll,1600);}catch(error){handleReadError(error);}}
function handleReadError(error){if(error.network||["SESSION_EXPIRED","CSRF_REJECTED"].includes(error.code)){network(false);state.failures++;if(state.failures<5&&state.job)state.timer=setTimeout(poll,Math.min(5000,800*2**state.failures));}else toast(error.message,true);}
async function submitRequest(requestPayload,mode){
  if(state.submitting)return;
  if(state.pending&&(state.pending.mode!==mode||JSON.stringify(state.pending.request)!==JSON.stringify(requestPayload))){text("form-error","原提交结果仍待查询，本次新要求未发送。请先查询原提交；只有点击“重试原提交”才会重试原要求与模式。");show("form-error");renderPending();return;}
  state.submitting=true;show("form-error",false);$("run-button").disabled=true;text("run-button","正在提交…");
  const pending=state.pending||{request:requestPayload,mode,submission_id:newId("SUB")};state.pending=pending;rememberSubmission(pending.submission_id);renderPending();
  try{const data=await api("/api/runs",{method:"POST",body:pending});await loadRun(data.run.run_id,true);state.pending=null;rememberSubmission(null);toast(data.reused?"已找回同一次提交的实际运行。":"任务已接收，正在后台处理。");}
  catch(error){text("form-error",error.network?"提交结果待查询，请恢复连接后查询或明确重试原提交。":error.message);show("form-error");if(!error.network){state.pending=null;rememberSubmission(null);}}
  finally{state.submitting=false;renderPending();$("run-button").disabled=false;$("run-button").replaceChildren(document.createTextNode("审核并生成草稿 "),el("span",null,"→"));}
}
async function reconnect(){try{await bootstrap();if(state.pending){const existing=await api("/api/submissions/"+encodeURIComponent(state.pending.submission_id));await loadRun(existing.run.run_id,true);state.pending=null;rememberSubmission(null);renderPending();show("form-error",false);}else if(state.job)await loadRun(state.job.run_id,false);toast("已恢复连接，并查询实际状态。");}catch(error){if(error.code==="RUN_NOT_FOUND"){text("form-error","未查询到原提交。可明确点击“重试原提交”复用原操作编号；当前新要求不会替换原请求。");show("form-error");renderPending();}else handleReadError(error);}}
function changeView(view){state.view=view;for(const name of ["materials","drafts","traces"])show(name+"-view",name===view);document.querySelectorAll(".nav-item").forEach(button=>button.classList.toggle("active",button.dataset.view===view));text("page-title",{materials:"素材审核与排期",drafts:"排期草稿",traces:"执行记录"}[view]);text("page-description",{materials:"看清素材风险，确认每一次排期调整。",drafts:"把原始要求、当前建议与确认状态放在一起。",traces:"回到每一个实际动作，核对结果从何而来。"}[view]);}

document.querySelectorAll("[data-view]").forEach(button=>button.addEventListener("click",()=>changeView(button.dataset.view)));
document.querySelectorAll("[data-close]").forEach(button=>button.addEventListener("click",()=>$(button.dataset.close).close()));
$("confirm-dialog").addEventListener("close",()=>{state.confirmation=null;});$("confirm-submit").addEventListener("click",confirmDraft);
$("pending-query").addEventListener("click",reconnect);$("pending-retry").addEventListener("click",retryPendingSubmission);
$("filters").addEventListener("click",event=>{const button=event.target.closest("[data-filter]");if(!button)return;state.filter=button.dataset.filter;$("filters").querySelectorAll("button").forEach(node=>node.classList.toggle("active",node===button));renderMaterials();});
$("select-all").addEventListener("change",()=>{const ids=Array.from($("material-rows").children).map(row=>row.dataset.materialId).filter(Boolean);for(const id of ids)$("select-all").checked?state.selected.add(id):state.selected.delete(id);updatePreview();renderMaterials();});
$("model-mode").addEventListener("change",modeHint);$("json-mode").addEventListener("change",()=>{for(const id of ["target-date","target-time"])$(id).required=!$("json-mode").checked;updatePreview();renderMaterials();});
for(const input of $("request-form").querySelectorAll("input,select")){if(!["model-mode","json-mode","json-file"].includes(input.id))input.addEventListener("change",()=>{if(input.id==="target-date"){const date=$("target-date").value;$("window-start").value=date+"T18:00";$("window-end").value=date+"T21:00";}updatePreview();if(input.id==="channel")bootstrap().catch(handleReadError);});}
$("json-file").addEventListener("change",async event=>{const file=event.target.files[0];if(!file)return;if(file.size>1048576){toast("JSON 文件不能超过 1 MiB。",true);return;}$("json-input").value=await file.text();$("json-mode").checked=true;$("json-mode").dispatchEvent(new Event("change"));toast("已导入原始 JSON，提交时由服务端严格校验。");});
$("request-form").addEventListener("submit",event=>{event.preventDefault();try{submitRequest(requestForSubmit(),$("model-mode").value);}catch(error){text("form-error",error.message);show("form-error");}});
$("new-request").addEventListener("click",()=>{if(state.submitting||state.pending){toast("原提交结果尚未查明，请先查询或明确重试原提交。",true);return;}state.loadEpoch=(state.loadEpoch||0)+1;state.formId=newId("REQ-WEB");state.signature=null;state.pending=null;state.job=null;state.events=[];state.cursor=0;clearTimeout(state.timer);$("json-mode").checked=false;$("model-mode").value="mock";modeHint();show("form-error",false);updatePreview();render();toast("已准备新任务，已有草稿仍保留在账本中。");});
$("refresh").addEventListener("click",()=>refreshFacts().then(()=>toast("已同步账本。读取操作不会重新运行模型。")).catch(handleReadError));$("reconnect").addEventListener("click",reconnect);
$("revalidate").addEventListener("click",()=>state.job&&revalidate(state.job.request_id));$("retry-run").addEventListener("click",()=>state.job&&submitRequest(state.job.request,state.job.mode));
$("download-trace").addEventListener("click",()=>{if(!state.job)return;const link=el("a");link.href="/api/runs/"+encodeURIComponent(state.job.run_id)+"/trace";link.download=state.job.run_id+".jsonl";link.click();});
document.addEventListener("visibilitychange",()=>{if(!document.hidden&&state.job&&["QUEUED","RUNNING"].includes(state.job.status)){clearTimeout(state.timer);poll();}});
bootstrap().then(async()=>{let remembered,pending;try{remembered=localStorage.getItem("yingshu-last-run");pending=localStorage.getItem("yingshu-pending-submission");}catch{}if(pending){try{const existing=await api("/api/submissions/"+encodeURIComponent(pending));await loadRun(existing.run.run_id,false);rememberSubmission(null);return;}catch(error){if(error.code!=="RUN_NOT_FOUND")throw error;text("form-error","未查询到刷新前的提交，请核对运行历史与原始要求后再操作。");show("form-error");rememberSubmission(null);}}const run=state.runs.find(run=>run.run_id===remembered)||state.runs[0];if(run)await loadRun(run.run_id,false);}).catch(handleReadError);
