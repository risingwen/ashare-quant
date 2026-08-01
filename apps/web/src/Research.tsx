import {useEffect, useState} from 'react';
import {useQuery} from '@tanstack/react-query';

const api=async(path:string)=>{const response=await fetch(`/api/v1${path}`);if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json()};

export default function Research(){
  const [tab,setTab]=useState<'survey'|'broker'>('survey');
  const [surveyDate,setSurveyDate]=useState('');
  const [month,setMonth]=useState('');
  const [query,setQuery]=useState('');
  const surveyDates=useQuery({queryKey:['survey-dates'],queryFn:()=>api('/research/survey-dates')});
  const brokerMonths=useQuery({queryKey:['broker-months'],queryFn:()=>api('/research/broker-months')});
  useEffect(()=>{const latest=surveyDates.data?.data?.[0]?.survey_date;if(latest&&!surveyDate)setSurveyDate(String(latest))},[surveyDates.data,surveyDate]);
  useEffect(()=>{const latest=brokerMonths.data?.data?.[0]?.month;if(latest&&!month)setMonth(String(latest))},[brokerMonths.data,month]);
  const surveys=useQuery({queryKey:['surveys',surveyDate,query],queryFn:()=>api(`/research/surveys?survey_date=${surveyDate}&q=${encodeURIComponent(query)}&limit=300`),enabled:tab==='survey'&&!!surveyDate});
  const brokers=useQuery({queryKey:['broker-recommendations',month,query],queryFn:()=>api(`/research/broker-recommendations?month=${month}&q=${encodeURIComponent(query)}&limit=1000`),enabled:tab==='broker'&&!!month});
  const surveyRows=surveys.data?.data||[];
  const brokerRows=brokers.data?.data||[];
  const uniqueStocks=new Set((tab==='survey'?surveyRows:brokerRows).map((row:any)=>row.symbol)).size;
  const uniqueBrokers=new Set(brokerRows.map((row:any)=>row.broker)).size;
  return <>
    <div className="page-title"><div><span className="eyebrow">INSTITUTIONAL INTELLIGENCE</span><h1>机构研究</h1><p className="muted">机构调研记录与券商月度金股，保留来源口径，不将推荐直接解释为投资信号。</p></div><div className="research-controls"><div className="segmented source-switch"><button className={tab==='survey'?'active':''} onClick={()=>setTab('survey')}>机构调研</button><button className={tab==='broker'?'active':''} onClick={()=>setTab('broker')}>券商金股</button></div>{tab==='survey'?<select value={surveyDate} onChange={e=>setSurveyDate(e.target.value)}>{(surveyDates.data?.data||[]).map((item:any)=><option value={item.survey_date} key={item.survey_date}>{item.survey_date}</option>)}</select>:<select value={month} onChange={e=>setMonth(e.target.value)}>{(brokerMonths.data?.data||[]).map((item:any)=><option value={item.month} key={item.month}>{String(item.month).slice(0,4)}-{String(item.month).slice(4)}</option>)}</select>}<input value={query} onChange={e=>setQuery(e.target.value)} placeholder="股票 / 机构 / 券商"/></div></div>
    <div className="cards"><div className="card"><span>{tab==='survey'?'调研记录':'推荐记录'}</span><strong>{tab==='survey'?surveyRows.length:brokerRows.length}</strong></div><div className="card"><span>涉及股票</span><strong>{uniqueStocks}</strong></div><div className="card"><span>{tab==='survey'?'数据日期':'参与券商'}</span><strong>{tab==='survey'?(surveyDate||'—'):uniqueBrokers}</strong></div><div className="card"><span>数据接口</span><strong>{tab==='survey'?'stk_surv':'broker_recommend'}</strong></div></div>
    {tab==='survey'?<section className="panel table-panel"><div className="panel-head"><div><span className="section-kicker">SURVEY RECORDS</span><h2>机构调研明细</h2></div><span className="chip">Tushare doc 275</span></div><div className="table-wrap"><table><thead><tr><th>股票</th><th>调研机构</th><th>机构类型</th><th>接待方式</th><th>接待地点</th><th>公司接待人员</th><th>调研内容</th></tr></thead><tbody>{surveyRows.map((row:any)=><tr key={row.record_key}><td><b>{row.name||row.symbol}</b><small>{row.symbol}</small></td><td><b>{row.receive_org||'—'}</b><small>{row.fund_visitors||'—'}</small></td><td>{row.org_type||'—'}</td><td>{row.receive_mode||'—'}</td><td>{row.receive_place||'—'}</td><td>{row.company_receivers||'—'}</td><td><span className="research-content" title={row.content||''}>{row.content||'—'}</span></td></tr>)}</tbody></table>{!surveyRows.length&&<div className="empty">所选日期暂无机构调研记录</div>}</div></section>:<section className="panel table-panel"><div className="panel-head"><div><span className="section-kicker">MONTHLY PICKS</span><h2>券商月度金股</h2></div><span className="chip">Tushare doc 267</span></div><div className="table-wrap"><table><thead><tr><th>股票</th><th>券商</th><th>当月被推荐次数</th><th>月份</th></tr></thead><tbody>{brokerRows.map((row:any)=><tr key={`${row.month}-${row.broker}-${row.symbol}`}><td><b>{row.name||row.symbol}</b><small>{row.symbol}</small></td><td>{row.broker}</td><td><b>{row.recommendation_count}</b></td><td>{String(row.month).slice(0,4)}-{String(row.month).slice(4)}</td></tr>)}</tbody></table>{!brokerRows.length&&<div className="empty">所选月份暂无券商金股记录</div>}</div></section>}
  </>;
}
