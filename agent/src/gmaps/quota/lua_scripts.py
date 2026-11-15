"""Redis Lua scripts for atomic quota reserve and refund."""

from __future__ import annotations

# Reserve all billable units or deny without partial increments.
# KEYS[1] = monthly SKU index set key
# KEYS[2..n+1] = monthly counter keys
# KEYS[n+2] = daily SKU index set key
# KEYS[n+3..2n+2] = daily counter keys
# ARGV[1] = event count (n)
# ARGV per event i (1-based): units, cap (-1 = unlimited), sku name (for SADD index)
RESERVE_QUOTA_SCRIPT = """
local n = tonumber(ARGV[1])
local month_index_key = KEYS[1]
local day_index_key = KEYS[n + 2]

for i = 1, n do
  local base = (i - 1) * 3 + 2
  local units = tonumber(ARGV[base])
  local cap = tonumber(ARGV[base + 1])
  local current = tonumber(redis.call('GET', KEYS[i + 1]) or '0')
  if cap >= 0 and current + units > cap then
    local sku = ARGV[base + 2]
    return {0, sku, current, cap}
  end
end

local new_totals = {}
for i = 1, n do
  local base = (i - 1) * 3 + 2
  local units = tonumber(ARGV[base])
  local sku = ARGV[base + 2]
  local new_val = redis.call('INCRBY', KEYS[i + 1], units)
  redis.call('SADD', month_index_key, sku)
  redis.call('INCRBY', KEYS[n + 2 + i], units)
  redis.call('SADD', day_index_key, sku)
  new_totals[i] = new_val
end

return {1, unpack(new_totals)}
"""

# Refund after a failed Google call when units were reserved.
# KEYS[1..n] = monthly counter keys; KEYS[n+1..2n] = daily counter keys
# ARGV[1] = n, then n times units
REFUND_QUOTA_SCRIPT = """
local n = tonumber(ARGV[1])
for i = 1, n do
  local units = tonumber(ARGV[i + 1])
  local key = KEYS[i]
  local current = tonumber(redis.call('GET', key) or '0')
  local refund = units
  if current < refund then
    refund = current
  end
  if refund > 0 then
    redis.call('DECRBY', key, refund)
  end
  local day_key = KEYS[n + i]
  local day_current = tonumber(redis.call('GET', day_key) or '0')
  local day_refund = units
  if day_current < day_refund then
    day_refund = day_current
  end
  if day_refund > 0 then
    redis.call('DECRBY', day_key, day_refund)
  end
end
return 1
"""
