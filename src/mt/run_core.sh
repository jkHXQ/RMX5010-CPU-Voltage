#!/system/bin/sh
# Manual, version-bound peer test. No uploads, autoload, DVFS writes or rmmod.
set -eu
umask 077
HERE=$(CDPATH= cd "$(dirname "$0")" && pwd)
OUT=${1:-/sdcard/Download/CPU-voltage-MT-results}
mkdir -p "$OUT"
RUN=$(mktemp -d "$OUT/test.XXXXXX")
META=$RUN/device.txt
{
 echo 'TOOL=RMX5010_MT_SINGLE_V2'
 echo "MODEL=$(getprop ro.product.model)"
 echo "SOC=$(getprop ro.soc.model)"
 echo "KERNEL=$(uname -r)"
 echo "BUILD=$(getprop ro.build.display.id)"
 echo "FINGERPRINT=$(getprop ro.build.fingerprint)"
 echo "UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
 echo "ROOT_UID=$(id -u)"
 if [ -r /sys/class/power_supply/battery/temp ]; then echo "BATTERY_TEMP_TENTHS_C=$(cat /sys/class/power_supply/battery/temp)"; fi
 echo 'PRIVACY=no serial/IMEI/Android-ID collected; no network uploads'
} > "$META"
fail() { echo "STATUS=FAILED: $*" | tee "$RUN/status.txt"; echo "诊断信息：$RUN"; exit 1; }
[ "$(id -u)" = 0 ] || fail '需要 root。请按说明使用 su -c sh 运行。'
[ "$(getprop ro.product.model)" = RMX5010 ] && [ "$(getprop ro.soc.model)" = SM8750 ] || fail '只支持 RMX5010 / SM8750。未加载模块。'
[ "$(uname -r)" = 6.6.89-android15-8-g7e1f3c083cc6-abogki467167594-4k ] || fail '内核版本不匹配。未加载新模块，请把 device.txt 发给作者适配。'
SLOT=$(getprop ro.boot.slot_suffix)
case "$SLOT" in _a|_b) ;; *) fail '活动槽位无效';; esac
FW=$(sha256sum "/dev/block/by-name/cpucp$SLOT" | cut -d ' ' -f 1)
echo "CPUCP_SHA256=$FW" >> "$META"
[ "$FW" = 2a2b9ce917e06cd4aafdfc4cd42c9cf63c7e627df46f7682f3769f38121662c5 ] || fail 'CPUCP 固件不同。未加载新模块，不套用本版公式。'
[ "$(sha256sum /sys/module/qcom_scmi_vendor/notes/.note.gnu.build-id | cut -d ' ' -f 1)" = bc3191abc43b3328e29435a58827e5592475e4249b3feaf54385157392f0a278 ] || fail '原厂 SCMI 模块 ABI 基线不同。未加载新模块。'
# File hashes inserted by the local release builder after files are finalized.
[ "$(sha256sum "$HERE/decode_score.awk" | cut -d ' ' -f 1)" = c8193402f9ecf7a6d9bb85a0283f82aa0f8f75bfdaa7cd29ecb29c150bb851f4 ] || fail '解析器校验失败'
[ "$(sha256sum "$HERE/reference_author.txt" | cut -d ' ' -f 1)" = 114fd98ee704b49653dc6426182ae40713cd5d59fc503006ccebabc6095a8513 ] || fail '原作者参考表校验失败'
MOD=/sys/module/live_voltage_scmi_v1
if [ ! -d "$MOD" ]; then
 [ "$(sha256sum "$HERE/live_voltage_scmi_v1.ko" | cut -d ' ' -f 1)" = 64e282e42f3208358843c494f1340a4a6cba94edabe59b8d419a29189aec79b4 ] || fail 'KO 校验失败'
 insmod "$HERE/live_voltage_scmi_v1.ko" || fail '模块加载失败。不要强制加载或绕过校验。'
fi
[ "$(sha256sum "$MOD/notes/.note.gnu.build-id" | cut -d ' ' -f 1)" = ae461bbd0c810f2b9134dbece68973d882fac00fd0b4b9a955919fb11fa4b353 ] || fail '同名诊断模块版本不匹配'
echo '正在执行两次 CPUCP 新查询，不修改频率或电压……'
cat "$MOD/parameters/sample" > "$RUN/sample1.txt" || fail '第一次查询读取失败'
sleep 1
cat "$MOD/parameters/sample" > "$RUN/sample2.txt" || fail '第二次查询读取失败'
if ! awk -v json="$RUN/result.json" -f "$HERE/decode_score.awk" "$HERE/reference_author.txt" "$RUN/sample1.txt" "$RUN/sample2.txt" > "$RUN/report.txt"; then
 cat "$RUN/report.txt"
 fail '表格或评分验证失败；不提供有效评分，原始数据已保留。'
fi
echo 'STATUS=VALID_TABLE' > "$RUN/status.txt"
{
 cat "$META"; echo; cat "$RUN/report.txt"
 echo; echo '=== RAW_SAMPLE_1 ==='; cat "$RUN/sample1.txt"
 echo; echo '=== RAW_SAMPLE_2 ==='; cat "$RUN/sample2.txt"
} > "$RUN/分享结果.txt"
if [ -t 1 ]; then
 awk 'BEGIN {c=sprintf("%c[36m",27);e=sprintf("%c[0m",27)} {if($0 ~ /^@/ || $0 ~ /非标准量化得分|这是原作者的体质/)print c $0 e;else print}' "$RUN/report.txt"
else
 cat "$RUN/report.txt"
fi
echo "分享这个文件：$RUN/分享结果.txt"
echo "结构化结果：$RUN/result.json"
echo '模块只在查询时工作，不自启。不要 rmmod；正常重启即可清除。'
