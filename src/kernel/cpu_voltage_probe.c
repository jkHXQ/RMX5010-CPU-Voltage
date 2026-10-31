// SPDX-License-Identifier: GPL-2.0-only
/* Read-only standard SCMI PERF wire queries, not Linux's cached est_power_get.
 * No MMIO mapping, no writes to CPU frequency/voltage, no hook or unload path.
 * ABI checked against this phone's loaded qcom_scmi_vendor.ko build-id.
 */
#include <linux/build_bug.h>
#include <linux/err.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/qcom_scmi_vendor.h>
#include <linux/scmi_protocol.h>
#include <asm/unaligned.h>
#include "protocols.h"

static_assert(offsetof(struct scmi_device, handle) == 0x3b8);
static_assert(offsetof(struct scmi_handle, devm_protocol_get) == 0x18);
static_assert(offsetof(struct scmi_protocol_handle, xops) == 8);
static_assert(offsetof(struct scmi_xfer_ops, xfer_get_init) == 8);
static_assert(offsetof(struct scmi_xfer_ops, do_xfer) == 0x18);
static_assert(offsetof(struct scmi_xfer_ops, xfer_put) == 0x28);
static_assert(offsetof(struct scmi_xfer, tx.buf) == 0x18);
static_assert(offsetof(struct scmi_xfer, rx.buf) == 0x28);
static_assert(offsetof(struct scmi_xfer, rx.len) == 0x30);

static DEFINE_MUTEX(query_lock);
static unsigned int sample_id;
static unsigned int queries;
static unsigned int report_len;
static char report[4096];
static unsigned int init_reached;
module_param(init_reached, uint, 0400);

#define OUT(fmt, ...) do { \
 if (report_len < sizeof(report)-1) \
  report_len += scnprintf(report+report_len, sizeof(report)-report_len, fmt, ##__VA_ARGS__); \
} while (0)

static int wire_query(const struct scmi_protocol_handle *ph, u8 id,
                      const u32 *tx, unsigned int words, u8 *reply, size_t *len)
{
 struct scmi_xfer *t = NULL;
 unsigned int i;
 int rc;
 /* Closed allowlist: VERSION, ATTRIBUTES, DOMAIN_ATTRIBUTES, DESCRIBE_LEVELS,
  * LEVEL_GET. In particular, no LIMITS_SET or LEVEL_SET messages. */
 if (!((id==0 && words==0) || (id==1 && words==0) ||
       (id==3 && words==1) || (id==4 && words==2) || (id==8 && words==1)))
  return -EINVAL;
 rc = ph->xops->xfer_get_init(ph, id, words*4, 128, &t);
 if (rc) return rc;
 if (!t || !t->tx.buf || !t->rx.buf) { rc=-EPROTO; goto done; }
 for (i=0; i<words; i++) put_unaligned_le32(tx[i], (u8 *)t->tx.buf+i*4);
 queries++;
 rc = ph->xops->do_xfer(ph, t);
 if (rc) goto done;
 if (t->rx.len > 128) { rc=-EMSGSIZE; goto done; }
 *len=t->rx.len;
 memcpy(reply, t->rx.buf, *len);
done:
 ph->xops->xfer_put(ph, t);
 return rc;
}

static int collect(struct scmi_protocol_handle *ph)
{
 u8 rx[128];
 size_t len=0;
 u32 tx[2], version, attr, d, first, n, remaining, j, v;
 int rc;
 /* Exact KCFI hashes from the current original vendor module's callsites.
  * Offsets were independently matched against its ARM64 instructions. */
 if (!ph || !ph->xops || !ph->xops->xfer_get_init || !ph->xops->do_xfer || !ph->xops->xfer_put)
  return -ENODEV;
 if (READ_ONCE(*(u32 *)((unsigned long)ph->xops->xfer_get_init-4)) != 0x85d53e14 ||
     READ_ONCE(*(u32 *)((unsigned long)ph->xops->do_xfer-4)) != 0xafb5eb25 ||
     READ_ONCE(*(u32 *)((unsigned long)ph->xops->xfer_put-4)) != 0x15fee88b)
  return -EPROTO;
 OUT("KCFI_XOPS_MATCH=1\n");
 rc=wire_query(ph,0,NULL,0,rx,&len); if(rc) return rc;
 if(len!=4) return -EPROTO;
 version=get_unaligned_le32(rx);
 OUT("VERSION=0x%x\n",version);
 if(version!=0x40000) return -EPROTO;
 rc=wire_query(ph,1,NULL,0,rx,&len); if(rc) return rc;
 if(len<16) return -EPROTO;
 attr=get_unaligned_le32(rx);
 OUT("ATTR=0x%x stats_lo=0x%x stats_hi=0x%x stats_size=%u\n",attr,
     get_unaligned_le32(rx+4),get_unaligned_le32(rx+8),get_unaligned_le32(rx+12));
 if(attr!=0x00020002) return -EPROTO;
 for(d=0;d<2;d++) {
  tx[0]=d;
  rc=wire_query(ph,3,tx,1,rx,&len); if(rc) return rc;
  if(len<32) return -EPROTO;
  OUT("DOMAIN=%u flags=0x%x sustained_khz=%u sustained_level=%u name=%.*s\n",d,
      get_unaligned_le32(rx),get_unaligned_le32(rx+8),get_unaligned_le32(rx+12),16,rx+16);
  first=0;
  while(first<16) {
   tx[0]=d; tx[1]=first;
   rc=wire_query(ph,4,tx,2,rx,&len); if(rc) return rc;
   if(len<4) return -EPROTO;
   n=get_unaligned_le16(rx); remaining=get_unaligned_le16(rx+2);
   if(!n || n>16-first || len!=4+n*20 || first+n+remaining!=16)
    return -EPROTO;
   for(j=0;j<n;j++) {
    u8 *p=rx+4+j*20;
    OUT("ROW %u %u %u %u %u %u %u\n",d,first+j,get_unaligned_le32(p),
        get_unaligned_le32(p+4),get_unaligned_le32(p+8),
        get_unaligned_le32(p+12),get_unaligned_le32(p+16));
   }
   first+=n;
  }
  tx[0]=d;
  rc=wire_query(ph,8,tx,1,rx,&len); if(rc) return rc;
  if(len!=4) return -EPROTO;
  v=get_unaligned_le32(rx);
  OUT("CURRENT_LEVEL %u %u\n",d,v);
 }
 return 0;
}

static int report_get(char *buf, const struct kernel_param *kp)
{
 struct scmi_device *sdev;
 struct scmi_protocol_handle *ph=NULL;
 const void *ops;
 int rc=-ENODEV, copied;
 mutex_lock(&query_lock);
 report_len=queries=0; report[0]=0; sample_id++;
 OUT("SAMPLE=%u read_only=1 source=FRESH_SCMI_WIRE_PROTOCOL_0x13\n",sample_id);
 OUT("ROW_FIELDS domain wire_index perf power_uW latency_raw indicative_freq level_index\n");
 sdev=get_qcom_scmi_device();
 if(IS_ERR_OR_NULL(sdev) || !sdev->handle || !sdev->handle->devm_protocol_get ||
    !sdev->handle->devm_protocol_put) goto out;
 ops=sdev->handle->devm_protocol_get(sdev, SCMI_PROTOCOL_PERF, &ph);
 if(IS_ERR(ops)) {rc=PTR_ERR(ops); goto out;}
 rc=collect(ph);
 sdev->handle->devm_protocol_put(sdev, SCMI_PROTOCOL_PERF);
out:
 OUT("RESULT rc=%d wire_queries=%u\n",rc,queries);
 copied=scnprintf(buf,4096,"%s",report);
 mutex_unlock(&query_lock);
 return copied;
}
static const struct kernel_param_ops report_ops={.get=report_get};
module_param_cb(sample,&report_ops,NULL,0400);

static int __init live_query_init(void)
{
 init_reached=1;
 pr_info("live_voltage_scmi_v1: standard SCMI GET only; no direct MMIO or DVFS writes\n");
 return 0;
}
module_init(live_query_init);
/* No module_exit: known unsafe unload path on this phone. No autoload files. */
MODULE_LICENSE("GPL");
MODULE_VERSION("1.0-get-only");
MODULE_DESCRIPTION("Fresh SCMI PERF read-only query; no cached est_power_get");
