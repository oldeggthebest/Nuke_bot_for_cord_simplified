# Nuke bot for cord (simplified)

The `!` command nuke toolkit. Prefix commands only - every command
operates on the server it is typed in. No slash commands, no web ui.

## Setup

```
pip install -r requirements.txt
echo "DISCORD_TOKEN=your bot token" > .env
python main.py
```

## proxies.txt - put your OWN proxies in

The attack traffic rotates through a proxy pool. Drop your own list
into `proxies.txt` at the repo root, one per line:

```
ip:port:user:pass
ip:port:user:pass
...
```

- no file (or an empty one) = everything goes direct from the host IP
- the pool carries **attack traffic only** - the gateway + bot REST
  stay direct so the bot never drops when the pool blinks
- dead proxies get quarantined with backoff automatically

## raid_message.txt

The text that `!spamchannels`, `!webhookspam` and the nuke drop into
channels. Edit freely.

## blacklist.json (optional)

A JSON list of user id strings that can never run a command:

```
["123456789012345678", "987654321098765432"]
```

## Commands

| command | what it does |
|---|---|
| `!nuke` | the full package - wipes + floods 500 channels, twice |
| `!banall` | ban every member |
| `!kickall` | kick every member |
| `!massdm` | DM every member (asks for the message) |
| `!nickall` | rename every member |
| `!mentionall` | ping everyone with @everyone |
| `!delchannels` | delete every channel |
| `!createchannels` | create 50 new channels |
| `!spamchannels` | spam the raid message in every channel |
| `!threadspam` | spawn threads in every channel |
| `!webhookspam` | webhook-spam every channel |
| `!delroles` | delete every role |
| `!createroles` | create 50 new roles |
| `!rename` | rename the server |
| `!emojis` | wipe every custom emoji |
| `!prune` | prune inactive members (7 days) |

1-minute cooldown between commands per user. Blacklisted users get
nothing.

## Structure

| path | what it is |
|---|---|
| `main.py` | entry point - .env token, proxies, loads every cog |
| `cogs/` | **one file per command** - `!nuke` lives in `cogs/nuke.py`, etc. |
| `cogs/common.py` | shared plumbing - cooldown, blacklist, the run wrapper |
| `core/attacks.py` | the attack engine (semaphore fan-out + REST client) |
| `core/proxies.py` | proxy pool + rotation |
| `core/patch429.py` | proper 429 retry handling |

yea i used ai don min it
