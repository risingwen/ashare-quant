import {useEffect, useState} from 'react';
import {useQuery} from '@tanstack/react-query';

const api=async(path:string)=>{const r=await fetch(`/api/v1${path}`);if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json()};
const money=(v:any)=>v==null?'—':`${(Number(v)/1e8).toFixed(2)}亿`;

export default function LongHu(){
  const [date,setDate]=useState(new Date().toISOString().slice(0,10));
  const [selected,setSelected]=useState<any>(null);
  const dates=useQuery({queryKey:['lhb-dates'],queryFn:()=>api('/lhb/dates')});
  useEffect(()=>{const latest=dates.data?.data?.[0]?.trade_date;if(latest)setDate(String(latest))},[dates.data]);
  const records=useQuery({queryKey:['lhb',date],queryFn:()=>api(`/lhb/records?trade_date=${date}&limit=200`)});
  const seats=useQuery({queryKey:['lhb-seats',date,selected?.symbol],queryFn:()=>api(`/lhb/seats?trade_date=${date}&symbol=${selected.symbol}&limit=100`),enabled:!!selected});
  const rows=records.data?.data||[]; const seatRows=seats.data?.data||[];
  const net=rows.reduce((s:number,r:any)=>s+Number(r.net_amount||0),0);
  return <><div className="page-title"><div><h1>龙虎榜</h1><p className="muted">交易所披露口径 · 个股榜单与席位穿透</p></div><input type="date" value={date} onChange={e=>{setDate(e.target.value);setSelected(null)}}/></div>
    <div className="cards"><div className="card"><span>上榜记录</span><strong>{rows.length}</strong></div><div className="card"><span>合计净买入</span><strong>{money(net)}</strong></div><div className="card"><span>最大净买入</span><strong>{money(rows[0]?.net_amount)}</strong></div><div className="card"><span>数据源</span><strong>Replay</strong></div></div>
    <div className="terminal-grid"><section><h2>当日榜单</h2><table><thead><tr><th>股票</th><th>涨跌幅</th><th>成交额</th><th>龙虎榜净额</th><th>上榜原因</th></tr></thead><tbody>{rows.map((r:any)=><tr className={selected?.symbol===r.symbol?'selected':''} onClick={()=>setSelected(r)} key={`${r.symbol}-${r.reason}`}><td><b>{r.name}</b><small>{r.symbol}</small></td><td className={Number(r.pct_change)>=0?'rise':'fall'}>{Number(r.pct_change||0).toFixed(2)}%</td><td>{money(r.amount)}</td><td className={Number(r.net_amount)>=0?'rise':'fall'}>{money(r.net_amount)}</td><td>{r.reason}</td></tr>)}</tbody></table></section>
    <aside><h2>{selected?`${selected.name} · 席位明细`:'选择一只股票'}</h2>{!selected?<div className="empty">点击左侧记录查看买卖席位</div>:<><div className="stock-summary"><span>净买入 {money(selected.net_amount)}</span><span>换手 {Number(selected.turnover_rate||0).toFixed(2)}%</span></div><table><thead><tr><th>营业部/机构</th><th>买入</th><th>卖出</th><th>净额</th></tr></thead><tbody>{seatRows.map((r:any)=><tr key={`${r.seat_name}-${r.side}`}><td>{r.seat_name}</td><td>{money(r.buy)}</td><td>{money(r.sell)}</td><td className={Number(r.net_buy)>=0?'rise':'fall'}>{money(r.net_buy)}</td></tr>)}</tbody></table></>}</aside></div></>
}
