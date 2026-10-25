//! swarm_db: the live state of the disaster-swarm simulation, served to every viewer by subscription.
//!
//! One generic table, `entity`, holds everything keyed by a path-like string ("drone/3", "metrics", "plan/1", "mesh/812",
//! ...): `text` carries JSON, `data` carries binary payloads (rasters, mesh chunks, point blocks). The simulator is the only
//! writer; viewers subscribe, and send commands through `submit_cmd`, which the simulator polls.
use spacetimedb::{Identity, ReducerContext, Table};

#[spacetimedb::table(accessor = entity, public)]
pub struct Entity {
    #[primary_key]
    pub key: String,
    pub ver: u64,
    pub text: String,
    pub data: Vec<u8>,
}

/// Mission log lines, append-only.
#[spacetimedb::table(accessor = event, public)]
pub struct Event {
    #[primary_key]
    #[auto_inc]
    pub seq: u64,
    pub t: f64,
    pub level: String,
    pub text: String,
}

/// Commands from viewers (play, pause, speed, step, reset ...) waiting for the simulator.
#[spacetimedb::table(accessor = cmd, public)]
pub struct Cmd {
    #[primary_key]
    #[auto_inc]
    pub seq: u64,
    pub name: String,
    pub args: String,
}

/// Who may write the simulation's state: the first identity to call `claim_writer` (the simulator's publisher, which keeps its
/// token). Until it is claimed anyone may write; afterwards only that identity. Viewers can only submit commands.
#[spacetimedb::table(accessor = writer)]
pub struct Writer {
    #[primary_key]
    pub id: u8,
    pub who: Identity,
}

fn allowed(ctx: &ReducerContext) -> bool {
    match ctx.db.writer().id().find(0u8) {
        Some(w) => w.who == ctx.sender(),
        None => true,
    }
}

#[spacetimedb::reducer]
pub fn claim_writer(ctx: &ReducerContext) {
    if ctx.db.writer().id().find(0u8).is_none() {
        ctx.db.writer().insert(Writer { id: 0, who: ctx.sender() });
    }
}

fn upsert(ctx: &ReducerContext, key: String, ver: u64, text: String, data: Vec<u8>) {
    ctx.db.entity().key().delete(&key);
    ctx.db.entity().insert(Entity { key, ver, text, data });
}

/// One row, with an optional binary payload.
#[spacetimedb::reducer]
pub fn put(ctx: &ReducerContext, key: String, ver: u64, text: String, data: Vec<u8>) {
    if !allowed(ctx) {
        return;
    }
    upsert(ctx, key, ver, text, data);
}

/// Many text rows in one call: `items` is a JSON array of [key, text] pairs.
#[spacetimedb::reducer]
pub fn put_many(ctx: &ReducerContext, items: String) {
    if !allowed(ctx) {
        return;
    }
    match serde_json::from_str::<Vec<(String, String)>>(&items) {
        Ok(rows) => {
            for (key, text) in rows {
                upsert(ctx, key, 0, text, Vec::new());
            }
        }
        Err(e) => log::warn!("put_many: bad items: {e}"),
    }
}

fn unhex(s: &str) -> Vec<u8> {
    let b = s.as_bytes();
    let v = |c: u8| match c {
        b'0'..=b'9' => c - b'0',
        b'a'..=b'f' => c - b'a' + 10,
        b'A'..=b'F' => c - b'A' + 10,
        _ => 0,
    };
    b.chunks(2).filter(|p| p.len() == 2).map(|p| (v(p[0]) << 4) | v(p[1])).collect()
}

/// Many binary rows in one call: `items` is a JSON array of [key, ver, text, hex-encoded data].
#[spacetimedb::reducer]
pub fn put_blobs(ctx: &ReducerContext, items: String) {
    if !allowed(ctx) {
        return;
    }
    match serde_json::from_str::<Vec<(String, u64, String, String)>>(&items) {
        Ok(rows) => {
            for (key, ver, text, hex) in rows {
                upsert(ctx, key, ver, text, unhex(&hex));
            }
        }
        Err(e) => log::warn!("put_blobs: bad items: {e}"),
    }
}

/// Delete rows by key.
#[spacetimedb::reducer]
pub fn drop_keys(ctx: &ReducerContext, keys: String) {
    if !allowed(ctx) {
        return;
    }
    if let Ok(list) = serde_json::from_str::<Vec<String>>(&keys) {
        for k in list {
            ctx.db.entity().key().delete(&k);
        }
    }
}

/// Mission log lines: `items` is a JSON array of [t, level, text].
#[spacetimedb::reducer]
pub fn add_events(ctx: &ReducerContext, items: String) {
    if !allowed(ctx) {
        return;
    }
    if let Ok(rows) = serde_json::from_str::<Vec<(f64, String, String)>>(&items) {
        for (t, level, text) in rows {
            ctx.db.event().insert(Event { seq: 0, t, level, text });
        }
    }
}

/// A viewer asks the simulator to do something.
#[spacetimedb::reducer]
pub fn submit_cmd(ctx: &ReducerContext, name: String, args: String) {
    ctx.db.cmd().insert(Cmd { seq: 0, name, args });
}

/// The simulator has taken the command.
#[spacetimedb::reducer]
pub fn ack_cmd(ctx: &ReducerContext, seq: u64) {
    if !allowed(ctx) {
        return;
    }
    ctx.db.cmd().seq().delete(&seq);
}

/// A new mission: forget everything.
#[spacetimedb::reducer]
pub fn clear_all(ctx: &ReducerContext) {
    if !allowed(ctx) {
        return;
    }
    let keys: Vec<String> = ctx.db.entity().iter().map(|r| r.key).collect();
    for k in keys {
        ctx.db.entity().key().delete(&k);
    }
    let evs: Vec<u64> = ctx.db.event().iter().map(|r| r.seq).collect();
    for s in evs {
        ctx.db.event().seq().delete(&s);
    }
}
