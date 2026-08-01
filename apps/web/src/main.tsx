import React, {Suspense, lazy, useEffect, useMemo, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {QueryClient, QueryClientProvider, useQuery} from '@tanstack/react-query';
import './style.css';
import {pageFromPath, pagePaths, type PageId} from './routing';

const Popularity = lazy(() => import('./Popularity'));
const LongHu = lazy(() => import('./LongHu'));
const MoneyFlow = lazy(() => import('./MoneyFlow'));
const Research = lazy(() => import('./Research'));

const api = async (path: string) => {
  const response = await fetch(`/api/v1${path}`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
};
const number = (v: unknown) => v == null ? '—' : new Intl.NumberFormat('zh-CN').format(Number(v));
const dateTime = (v: unknown) => v ? new Date(String(v)).toLocaleString('zh-CN', {hour12:false}) : '—';

function Loading({label='正在载入数据'}:{label?:string}) { return <div className="loading"><i/><span>{label}</span></div>; }
function ErrorState({error}:{error:unknown}) { return <div className="error-panel"><b>数据暂不可用</b><span>{String(error)}</span></div>; }
function Metric({label,value,detail,tone}:{label:string,value:React.ReactNode,detail?:string,tone?:string}) {
  return <div className={`metric ${tone||''}`}><span>{label}</span><strong>{value}</strong>{detail&&<small>{detail}</small>}</div>;
}

function Overview() {
  const overview=useQuery({queryKey:['overview'],queryFn:()=>api('/overview')});
  const backfill=useQuery({queryKey:['backfill'],queryFn:()=>api('/backfill-status'),refetchInterval:30000});
  if (overview.isLoading) return <Loading/>;
  if (overview.error) return <ErrorState error={overview.error}/>;
  const d=overview.data?.data||{};
  const progress=backfill.data?.data||[];
  const datasets=['daily','dc_hot','ths_hot','moneyflow_dc','moneyflow_ind_dc','top_list','top_inst'];
  const expected=Number(d.trade_day_count||1);
  const complete=datasets.filter(x=>progress.some((r:any)=>r.dataset===x&&r.status==='success'&&Number(r.day_count)>=expected)).length;
  return <>
    <div className="hero"><div><span className="eyebrow">RESEARCH CONTROL CENTER</span><h1>市场研究总览</h1><p>从数据质量到策略验证，在同一条可追溯工作流中完成。</p></div><div className="market-state"><i/>数据服务正常<span>截至 {d.latest_date||'—'}</span></div></div>
    <div className="metric-grid">
      <Metric label="最新交易日" value={d.latest_date} detail="日线与研究因子对齐"/>
      <Metric label="A 股标的" value={number(d.instrument_count)} detail="当前证券主数据"/>
      <Metric label="当日人气记录" value={`${number(d.dc_snapshot_count)} / ${number(d.ths_snapshot_count)}`} detail="东财 / 同花顺最终快照 Top100"/>
      <Metric label="数据集就绪" value={`${complete} / ${datasets.length}`} detail="2025 年以来历史覆盖" tone={complete===datasets.length?'good':''}/>
    </div>
    <div className="dashboard-grid">
      <section className="panel span-2"><div className="panel-head"><div><span className="section-kicker">WORKFLOW</span><h2>研究流水线</h2></div><span className="chip">Replay only</span></div>
        <div className="pipeline">
          {[['01','市场数据','日线 / 人气 / 龙虎榜','ready'],['02','因子研究','排名变化与事件信号','ready'],['03','策略实验',`${number(d.strategy_run_count)} 次可复现实验`,'active'],['04','模拟组合','仓位与净值跟踪','active']].map(([n,t,s,state],i)=><React.Fragment key={n}><div className={`pipe-step ${state}`}><b>{n}</b><div><strong>{t}</strong><span>{s}</span></div></div>{i<3&&<div className="pipe-line"/>}</React.Fragment>)}
        </div>
      </section>
      <section className="panel"><div className="panel-head"><div><span className="section-kicker">DATA HEALTH</span><h2>数据覆盖</h2></div></div>
        <div className="health-list">{datasets.map(name=>{const row=progress.find((r:any)=>r.dataset===name&&r.status==='success');const pct=Math.min(100,Math.round(Number(row?.day_count||0)/expected*100));return <div key={name}><div><b>{name}</b><span>{pct}% · {number(row?.row_count)} 行</span></div><em><i style={{width:`${pct}%`}}/></em></div>})}</div>
      </section>
      <section className="panel"><div className="panel-head"><div><span className="section-kicker">TODAY</span><h2>研究焦点</h2></div></div>
        <div className="focus-list"><div><b>人气异动</b><span>查看跨平台排名与盘中轨迹</span><strong>进入研究 →</strong></div><div><b>龙虎榜资金</b><span>从个股下钻至营业部席位</span><strong>查看榜单 →</strong></div><div><b>策略实验</b><span>参数、数据版本与结果留痕</span><strong>管理实验 →</strong></div></div>
      </section>
    </div>
  </>;
}

function Strategies(){
  const q=useQuery({queryKey:['strategy-runs'],queryFn:()=>api('/strategy-runs')});
  if(q.isLoading)return <Loading/>; if(q.error)return <ErrorState error={q.error}/>;
  const rows=q.data?.data||[];
  return <><div className="hero compact"><div><span className="eyebrow">EXPERIMENT LAB</span><h1>策略实验</h1><p>先把每个研究假设做成可复现、可比较、可反驳的实验，再考虑自动化选参。</p></div><span className="chip">研究模式 · 暂不开放网页创建</span></div>
    <div className="metric-grid"><Metric label="实验总数" value={rows.length}/><Metric label="运行成功" value={rows.filter((r:any)=>r.status==='success').length} tone="good"/><Metric label="当前阶段" value="验证框架" detail="不急于扩充策略数量"/><Metric label="下一门禁" value="样本外" detail="滚动窗口与基准比较"/></div>
    <section className="panel"><div className="panel-head"><div><span className="section-kicker">RECOMMENDED WORKFLOW</span><h2>建议按三层推进</h2></div><span className="chip">参考主流量化研究工作流</span></div><div className="recommendation-grid"><article><b>P0 · 实验账本</b><p>固定数据版本、代码指纹、参数、费用与信号时点；相同输入必须得到相同结果。</p></article><article><b>P1 · 样本外验证</b><p>加入滚动训练/验证窗口、基准指数、行业中性对照和交易成本压力测试。</p></article><article><b>P2 · 稳健性而非最优点</b><p>展示参数热力图、换手与容量；优先选择稳定参数区域，不追逐单一最佳收益。</p></article></div></section>
    <section className="panel table-panel"><div className="panel-head"><div><span className="section-kicker">RUN HISTORY</span><h2>实验记录</h2></div><button className="ghost">筛选</button></div><div className="table-wrap"><table><thead><tr><th>策略模板</th><th>样本区间</th><th>参数</th><th>数据版本</th><th>状态</th><th>完成时间</th></tr></thead><tbody>{rows.map((r:any)=><tr key={r.id}><td><b>{r.template_key}</b><small>版本 v{r.template_version}</small></td><td>{r.start_date}<small>至 {r.end_date}</small></td><td><code>{Object.entries(r.parameters||{}).map(([k,v])=>`${k}=${v}`).join(' · ')}</code></td><td className="mono clip">{r.data_version}</td><td><span className={`status ${r.status}`}>{r.status==='success'?'已完成':r.status}</span></td><td>{dateTime(r.finished_at)}</td></tr>)}</tbody></table></div></section>
  </>;
}

function Portfolio(){
  const q=useQuery({queryKey:['portfolio'],queryFn:()=>api('/portfolio')});
  if(q.isLoading)return <Loading/>; if(q.error)return <ErrorState error={q.error}/>;
  const rows=q.data?.data||[]; const p=rows[0]; const initial=Number(p?.initial_cash||0),cash=Number(p?.cash||0);
  return <><div className="hero compact"><div><span className="eyebrow">PAPER PORTFOLIO</span><h1>模拟组合</h1><p>定位为“策略上线前的执行沙盒”，只验证订单、仓位、风险与归因，不连接券商。</p></div><span className="live-pill"><i/>{p?'已有活动组合':'规划中'}</span></div>
    <div className="metric-grid"><Metric label="初始资金" value={p?`¥ ${number(initial)}`:'—'}/><Metric label="可用现金" value={p?`¥ ${number(cash)}`:'—'} detail={p?`${initial?((cash/initial)*100).toFixed(1):0}% 现金占比`:'尚未创建组合'}/><Metric label="当前阶段" value="执行设计" detail="先完成估值、风险和归因合同"/><Metric label="实盘连接" value="不启用" detail="研究用途模拟组合"/></div>
    <section className="panel"><div className="panel-head"><div><span className="section-kicker">MINIMUM USEFUL PORTFOLIO</span><h2>建议的最小可用范围</h2></div><span className="chip">暂缓扩展页面功能</span></div><div className="recommendation-grid"><article><b>事件账本</b><p>信号、预定订单、成交、撤单和失败原因按交易日串联，能回答每一笔仓位从哪里来。</p></article><article><b>净值与风险</b><p>现金、持仓市值、基准、回撤、行业集中度和单股风险使用同一估值时点。</p></article><article><b>执行归因</b><p>拆分信号收益、滑点、手续费、涨跌停/停牌未成交影响，避免只看一条净值曲线。</p></article></div></section>
    <div className="dashboard-grid"><section className="panel span-2"><div className="panel-head"><div><span className="section-kicker">EQUITY CURVE</span><h2>组合净值</h2></div></div><div className="empty-state">估值与基准合同完成后再绘制真实净值，不展示模拟占位曲线</div></section><section className="panel"><div className="panel-head"><div><span className="section-kicker">CONFIG</span><h2>组合设置</h2></div></div>{p?<dl className="details"><div><dt>组合名称</dt><dd>{p.name}</dd></div><div><dt>策略模板</dt><dd>{p.strategy_template_key}</dd></div><div><dt>最大持仓</dt><dd>{p.parameters?.max_positions||'—'}</dd></div><div><dt>人气阈值</dt><dd>前 {p.parameters?.rank_max||'—'}</dd></div><div><dt>创建时间</dt><dd>{dateTime(p.created_at)}</dd></div></dl>:<div className="empty-state">暂无模拟组合</div>}</section></div>
  </>;
}

function SystemPage(){
  const backfill=useQuery({queryKey:['backfill'],queryFn:()=>api('/backfill-status'),refetchInterval:15000});
  const batches=useQuery({queryKey:['data-status'],queryFn:()=>api('/data-status'),refetchInterval:15000});
  const freshness=useQuery({queryKey:['data-freshness'],queryFn:()=>api('/data-freshness'),refetchInterval:15000});
  const rows=backfill.data?.data||[], batchRows=batches.data?.data||[];
  const freshRows=freshness.data?.data||[], syncJobs=freshness.data?.jobs||[];
  const moneyflowJob=syncJobs.find((x:any)=>x.job_name==='moneyflow_sync');
  const popularityJob=syncJobs.find((x:any)=>x.job_name==='popularity_sync');
  const intelligenceJob=syncJobs.find((x:any)=>x.job_name==='market_intelligence_sync');
  const expected=Math.max(...rows.filter((x:any)=>x.dataset==='daily'&&x.status==='success').map((x:any)=>Number(x.day_count||0)),1);
  const grouped=useMemo(()=>['daily','dc_hot','ths_hot','moneyflow_dc','moneyflow_ind_dc','top_list','top_inst'].map(dataset=>({dataset,ok:rows.find((x:any)=>x.dataset===dataset&&x.status==='success'),issues:rows.filter((x:any)=>x.dataset===dataset&&x.status!=='success')})),[rows]);
  return <><div className="hero compact"><div><span className="eyebrow">OPERATIONS</span><h1>系统状态</h1><p>数据质量、历史覆盖和采集批次的统一观测面板。</p></div><span className="market-state"><i/>API 在线</span></div>
    <div className="metric-grid">{freshRows.filter((r:any)=>['daily','moneyflow_dc'].includes(r.dataset)).map((r:any)=><Metric key={r.dataset} label={r.dataset} value={r.latest_date||'—'} detail={`市场基准 ${r.expected_date||'—'} · ${r.status==='current'?'已同步':'已滞后'}`} tone={r.status==='current'?'good':''}/>) }<Metric label="热榜自动同步" value={popularityJob?.status==='success'?'正常':popularityJob?.status==='failed'?'重试中':'等待首轮'} detail={popularityJob?`最近运行 ${dateTime(popularityJob.finished_at||popularityJob.started_at)}`:'每日 23:05 执行'} tone={popularityJob?.status==='success'?'good':''}/><Metric label="资金流自动同步" value={moneyflowJob?.status==='success'?'正常':moneyflowJob?.status==='failed'?'重试中':'等待首轮'} detail={moneyflowJob?`最近运行 ${dateTime(moneyflowJob.finished_at||moneyflowJob.started_at)}`:'每日收盘后执行'} tone={moneyflowJob?.status==='success'?'good':''}/><Metric label="机构与游资同步" value={intelligenceJob?.status==='success'?'正常':intelligenceJob?.status==='failed'?'重试中':'等待首轮'} detail={intelligenceJob?`最近运行 ${dateTime(intelligenceJob.finished_at||intelligenceJob.started_at)}`:'随每日任务执行'} tone={intelligenceJob?.status==='success'?'good':''}/></div>
    <div className="service-grid">{grouped.map((g:any)=>{const fresh=freshRows.find((r:any)=>r.dataset===g.dataset);const hasGap=Number(fresh?.missing_count||0)>0;return <div className="service-card" key={g.dataset}><div><b>{g.dataset}</b><span className={g.issues.length||hasGap?'warn-dot':'ok-dot'}>{hasGap?`缺 ${fresh.missing_count} 日`:Number(g.ok?.day_count||0)<expected||g.issues.length?'补数中':'正常'}</span></div><strong>{g.ok?.day_count||0}<small> / {expected} 天</small></strong><span>{hasGap?`缺口：${(fresh.missing_dates||[]).join('、')}`:`${number(g.ok?.row_count)} 行 · 更新于 ${dateTime(g.ok?.updated_at)}`}</span></div>})}</div>
    <section className="panel table-panel"><div className="panel-head"><div><span className="section-kicker">INGESTION LOG</span><h2>最近采集批次</h2></div><span className="chip">15 秒刷新</span></div><div className="table-wrap"><table><thead><tr><th>批次</th><th>数据集</th><th>来源</th><th>记录数</th><th>状态</th><th>完成时间</th></tr></thead><tbody>{batchRows.slice(0,20).map((r:any)=><tr key={r.id}><td className="mono">#{r.id}</td><td><b>{r.dataset}</b></td><td>{r.provider}</td><td>{number(r.row_count)}</td><td><span className={`status ${r.status}`}>{r.status}</span></td><td>{dateTime(r.finished_at)}</td></tr>)}</tbody></table></div></section>
  </>;
}

const nav: [PageId,string,string][]=[['overview','总览','⌂'],['popularity','人气研究','↗'],['moneyflow','资金流','¥'],['lhb','龙虎榜','榜'],['research','机构研究','研'],['strategies','策略实验','◇'],['portfolio','模拟组合','◎'],['system','系统状态','◌']];
function App(){
  const [page,setPage]=useState<PageId>(()=>pageFromPath(location.pathname));
  useEffect(()=>{const onPopState=()=>setPage(pageFromPath(location.pathname));window.addEventListener('popstate',onPopState);return()=>window.removeEventListener('popstate',onPopState)},[]);
  const navigate=(next:PageId)=>{if(location.pathname!==pagePaths[next])history.pushState({},'',pagePaths[next]);setPage(next);window.scrollTo({top:0,behavior:'smooth'})};
  const views:Record<PageId,React.ReactNode>={overview:<Overview/>,popularity:<Suspense fallback={<Loading label="正在加载人气图表"/>}><Popularity/></Suspense>,moneyflow:<Suspense fallback={<Loading label="正在加载资金流"/>}><MoneyFlow/></Suspense>,lhb:<Suspense fallback={<Loading label="正在加载龙虎榜"/>}><LongHu/></Suspense>,research:<Suspense fallback={<Loading label="正在加载机构研究"/>}><Research/></Suspense>,strategies:<Strategies/>,portfolio:<Portfolio/>,system:<SystemPage/>};
  return <div className="app-shell"><aside className="sidebar"><div className="brand"><div>Q</div><span><b>QUANT LAB</b><small>A 股研究平台</small></span></div><nav>{nav.map(([id,label,icon])=><a href={pagePaths[id]} className={page===id?'active':''} onClick={e=>{e.preventDefault();navigate(id)}} key={id}><i>{icon}</i><span>{label}</span></a>)}</nav><div className="sidebar-foot"><span><i/>REPLAY</span><small>数据服务已连接</small></div></aside><div className="workspace"><header><div className="breadcrumb"><span>量化研究</span><b>/</b><strong>{nav.find(x=>x[0]===page)?.[1]}</strong></div><div className="header-tools"><a href="/docs.html#overview" target="_blank">文档</a><button title="刷新页面" onClick={()=>location.reload()}>↻</button><div className="avatar">研</div></div></header><main>{views[page]}</main></div></div>;
}

const client=new QueryClient({defaultOptions:{queries:{staleTime:30000,retry:1}}});
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={client}><App/></QueryClientProvider>);
