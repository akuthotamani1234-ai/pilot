"""Redis Lua scripts for the durable swarm queue.

Each script applies one status change only when the hash still matches the
state the caller is allowed to change.
"""

# Apply a hash update only while this worker still holds an unexpired lease.
HOLD_LEASE = """
local status = redis.call('HGET', KEYS[1], 'status')
local owner = redis.call('HGET', KEYS[1], 'lease_owner')
local until_s = redis.call('HGET', KEYS[1], 'lease_until')
if status ~= 'leased' or owner ~= ARGV[1] then
  return 0
end
local until_n = tonumber(until_s)
local now = tonumber(ARGV[2])
if until_n == nil or until_n < now then
  return 0
end
local i = 5
while i <= #ARGV do
  redis.call('HSET', KEYS[1], ARGV[i], ARGV[i + 1])
  i = i + 2
end
if ARGV[4] == '1' then
  redis.call('ZADD', KEYS[2], now, ARGV[3])
end
return 1
"""

# Requeue only while the task is still leased and the lease is already expired.
# A worker that claimed it again after this process read the hash keeps the task.
RECOVER_LEASE = """
local status = redis.call('HGET', KEYS[1], 'status')
if status ~= 'leased' then
  return 0
end
local until_n = tonumber(redis.call('HGET', KEYS[1], 'lease_until'))
local now = tonumber(ARGV[1])
if until_n ~= nil and until_n >= now then
  return 0
end
redis.call('HSET', KEYS[1],
  'status', ARGV[2],
  'lease_owner', '',
  'lease_until', '',
  'error_class', 'lease_expired',
  'updated_at', ARGV[1])
if ARGV[2] == 'retry_wait' then
  redis.call('ZADD', KEYS[2], now, ARGV[3])
end
return 1
"""

# Pop one waiting task and lease it in the same script.
# An empty queue returns ''. A stale id returns '0' and is not put back.
POP_CLAIM = """
local popped = redis.call('ZPOPMIN', KEYS[1])
if popped == nil or #popped == 0 then
  return ''
end
local task_id = popped[1]
local status = redis.call('HGET', ARGV[1] .. task_id, 'status')
if status ~= 'pending' and status ~= 'retry_wait' then
  return '0'
end
local current = tonumber(redis.call('HGET', ARGV[1] .. task_id, 'attempt')) or 0
redis.call('HSET', ARGV[1] .. task_id,
  'status', 'leased',
  'attempt', tostring(current + 1),
  'lease_owner', ARGV[3],
  'lease_until', ARGV[4],
  'updated_at', ARGV[2])
return task_id
"""

SET_TERMINAL = """
local status = redis.call('HGET', KEYS[1], 'status')
local allowed = false
local i = 5
while i <= #ARGV do
  if status == ARGV[i] then
    allowed = true
  end
  i = i + 1
end
if not allowed then
  return 0
end
redis.call('HSET', KEYS[1],
  'status', ARGV[2],
  'error_class', ARGV[3],
  'lease_owner', '',
  'lease_until', '',
  'updated_at', ARGV[1])
redis.call('ZREM', KEYS[2], ARGV[4])
return 1
"""

# One idempotency key inserts one hash. A second caller receives the first id.
ENQUEUE_ONCE = """
local existing = redis.call('GET', KEYS[1])
if existing and existing ~= '' then
  return existing
end
redis.call('SET', KEYS[1], ARGV[1])
local i = 3
while i <= #ARGV do
  redis.call('HSET', KEYS[2], ARGV[i], ARGV[i + 1])
  i = i + 2
end
redis.call('ZADD', KEYS[3], ARGV[2], ARGV[1])
redis.call('SADD', KEYS[4], ARGV[1])
return ARGV[1]
"""
