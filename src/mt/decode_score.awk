# CPUCP firmware-bound parser. Author-reference score is NOT a silicon grade.
BEGIN { bad=0; comparable=1; refcount=0 }
{sub(/\r$/, "")}
FILENAME==ARGV[1] {
 if($0 ~ /^#/ || NF==0) next
 if($1!="REF" || NF!=5 || $2 !~ /^[01]$/ || $3 !~ /^[0-9]+$/ || $4 !~ /^[0-9]+$/ || $5 !~ /^[0-9]+$/ || $3>15 || $4<=0 || $5<=0 || rseen[$2,$3]++) {bad++;next}
 rf[$2,$3]=$4;rv[$2,$3]=$5;refcount++;next
}
FILENAME==ARGV[2] {s=1}
FILENAME==ARGV[3] {s=2}
/^SAMPLE=[0-9]+ read_only=1 source=FRESH_SCMI_WIRE_PROTOCOL_0x13$/ {head[s]++;split($1,a,"=");sid[s]=a[2]}
/^KCFI_XOPS_MATCH=1$/ {kcfi[s]++}
/^VERSION=0x40000$/ {ver[s]++}
/^ATTR=0x20002 / {attr[s]++}
/^DOMAIN=[01] flags=0x6a000000 / {split($1,a,"=");domain[s,a[2]]++}
/^ROW / {
 if(NF!=8 || $2 !~ /^[01]$/ || $3 !~ /^[0-9]+$/ || $4 !~ /^[0-9]+$/ || $5 !~ /^[0-9]+$/ || $7 !~ /^[0-9]+$/ || $8 !~ /^[0-9]+$/ || $3!=$8 || $4!=$7 || $3>15 || $5<=0 || $7<=0 || seen[s,$2,$3]++) {bad++;next}
 c=($2==0)?100:136; mult=c*$7; p=$5
 lo=int(sqrt(p*1000000000/mult));if(lo*lo*mult<p*1000000000)lo++
 hi=int(sqrt(((p+1)*1000000000-1)/mult))
 if(lo!=hi || lo<=0 || lo*lo*c>=2147483648 || int(lo*lo*mult/1000000000)!=p) {bad++;next}
 f[s,$2,$3]=$7;v[s,$2,$3]=lo;power[s,$2,$3]=p;n[s]++
}
/^CURRENT_LEVEL [01] [0-9]+$/ {current[s,$2]++;current_index[s,$2]=$3}
/^RESULT / {result[s]++;rc[s]=$2;queries[s]=$3}
END {
 if(refcount!=32 || sid[2]<=sid[1])bad++
 for(s=1;s<=2;s++) {
  if(head[s]!=1 || kcfi[s]!=1 || ver[s]!=1 || attr[s]!=1 || domain[s,0]!=1 || domain[s,1]!=1 || n[s]!=32 || result[s]!=1 || queries[s]!="wire_queries=38")bad++
  complete=(rc[s]=="rc=0" && current[s,0]==1 && current[s,1]==1)
  partial[s]=(rc[s]=="rc=-22" && current[s,0]==1 && current[s,1]==0)
  if(!complete && !partial[s])bad++
 }
 for(d=0;d<2;d++)for(i=0;i<16;i++) {
  if(rseen[d,i]!=1 || seen[1,d,i]!=1 || seen[2,d,i]!=1 || f[1,d,i]!=f[2,d,i] || v[1,d,i]!=v[2,d,i])bad++
  if(f[1,d,i]!=rf[d,i])comparable=0
 }
 if(bad) {print "VALIDATION=FAILED";print "数据不完整、两次表不同、版本/协议不匹配或反解不唯一；不输出分数。请保留原始文件。";exit 1}
 print "CPUCP 现场查询 · 配置电压表（原算法反解）"
 print "非 PMIC 瞬时测量；两次新查询一致。"
 for(d=0;d<2;d++) {
  print "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@"
  if(d==0)printf "@ 6×Oryon 大核  CPU0–5  /  上限 %.2f GHz @\n",f[1,d,15]/1000000
  else printf "@ 2×Oryon 超大核 CPU6–7 / 上限 %.2f GHz @\n",f[1,d,15]/1000000
  print "@       频率 MHz          配置电压 mV   @"
  for(i=15;i>=0;i--) {
   printf "@    %9.1f MHz          %4d mV      @\n",f[1,d,i]/1000,v[1,d,i]
   weight=(i==15)?95:5
   score_sum[d]+=(1100-v[1,d,i])*weight
   author_sum[d]+=(1100-rv[d,i])*weight
  }
  score[d]=int(score_sum[d]/16);author[d]=int(author_sum[d]/16)
 }
 print "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@"
 print ""
 print "CPU体质非标准量化得分："
 printf "6×Oryon 大核：     %d 分\n",score[0]
 printf "2×Oryon 超大核：   %d 分\n",score[1]
 total=int((score[0]+score[1])/2);author_total=int((author[0]+author[1])/2)
 printf "综合参考分：      %d 分（两簇得分平均）\n",total
 print ""
 print "这是原作者的体质（参考机，不是官方标准）："
 printf "大核 %d 分 | 超大核 %d 分 | 综合 %d 分\n",author[0],author[1],author_total
 if(comparable)printf "与原作者相比：大核 %+d | 超大核 %+d | 综合 %+d\n",score[0]-author[0],score[1]-author[1],total-author_total
 else print "频点与原作者不同：仅列本机非标准分，不作跨机高低比较。"
 print ""
 print "调侃：这体质，转转 / 闲鱼挂上卖了吧 😂"
 print "（纯属玩笑；别凭这个分数判断故障或决定卖手机。）"
 print ""
 print "规则沿用原包大核分制：(1100-mV)×权重，再除以档位数。"
 print "最高频权重95，其余权重5；综合平均分为本版新增。"
 print "仅娱乐参考，不代表最低稳定电压、超频能力或官方体质。"
 for(s=1;s<=2;s++)if(partial[s])printf "注意：样本%d取表完整，但随后当前等级查询-22；当前等级不可用。\n",s
 if(json!="") {
  print "{" > json
  print "  \"schema\":\"rmx5010-mt-v2\",\"source\":\"fresh_scmi_power_unique_voltage_inversion\",\"direct_voltage_measurement\":false," >> json
  print "  \"score_method\":\"legacy_1100_minus_mv_top95_rest5_div16_truncate\",\"total_method\":\"integer_average_of_two_cluster_scores\",\"reference_zip_sha256\":\"debfb703327d8bc6990da776ff2c23c0c782ff4e9fda5f3786be24828788c535\"," >> json
  printf "  \"score\":%d,\"score_cluster0\":%d,\"score_cluster1\":%d,\"author_score\":%d,\"author_cluster0\":%d,\"author_cluster1\":%d,\n",total,score[0],score[1],author_total,author[0],author[1] >> json
  print "  \"scoring_comparable\":" (comparable?"true":"false") ",\"not_official_grade\":true," >> json
  printf "  \"sample_ids\":[%d,%d],\"current_level_query_rc\":[%d,%d],\n",sid[1],sid[2],partial[1]?-22:0,partial[2]?-22:0 >> json
  print "  \"rows\":[" >> json
  k=0;for(d=0;d<2;d++)for(i=0;i<16;i++) {
   if(k++)print "," >> json
   printf "    {\"domain\":%d,\"index\":%d,\"frequency_khz\":%d,\"voltage_mv_derived\":%d,\"raw_power_uw\":%d}",d,i,f[1,d,i],v[1,d,i],power[1,d,i] >> json
  }
  print "\n  ]\n}" >> json;close(json)
 }
}
