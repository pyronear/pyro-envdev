#!/usr/bin/env bash
# Replay the pyronear/roadmap#16 robustness tests on a test Pi.
#
# Runs ON the Pi (user with sudo, Docker installed), from any directory:
#   scp replay-robustness-tests.sh pi@<ip>:~ && ssh pi@<ip>
#   ./replay-robustness-tests.sh setup        # branch, images, fake cameras (20 to 30 min on a Pi 5)
#   ./replay-robustness-tests.sh 419          # engine frozen -> healthcheck restarts it      (~2 min)
#   ./replay-robustness-tests.sh 458-timeout  # Reolink call that hangs -> 10 s timeout       (~2 min)
#   ./replay-robustness-tests.sh 458-health   # camera API frozen -> healthcheck restarts it  (~3 min)
#   ./replay-robustness-tests.sh 459          # night per frame, 204 never proves night       (~15 min)
#   ./replay-robustness-tests.sh 461-silent   # no fresh image -> API reboot, budget on disk  (~18 min)
#   ./replay-robustness-tests.sh 461-frozen   # frozen + not_moving -> reboot, 30 min cooldown (~50 min)
#   ./replay-robustness-tests.sh all          # everything above, in that order (~90 min)
#   ./replay-robustness-tests.sh real         # back to the real cameras
#
# Needs: passwordless sudo, ~/pyro-engine checkout with a .env (CAM_USER, CAM_PWD, API_URL...) and
# data/credentials.json holding two cameras. Everything else is built by `setup`.
# The engine talks to API_URL with the real camera tokens: point it at preprod.
# Scenario timings follow the detector's own constants (5 min checks, 30 min cooldown).
set -euo pipefail

ENGINE_DIR=${ENGINE_DIR:-$HOME/pyro-engine}
ENVDEV_DIR=${ENVDEV_DIR:-$HOME/pyro-envdev}
TAG=${TAG:-robustness}
# pyro-engine PR branches merged on top of develop; BRANCHES= once they are merged
BRANCHES=${BRANCHES-"fix/heartbeat-signal-deadlock fix/engine-day-night-per-frame feat/camera-recovery"}
FAKE_NET=fakecams
FAKE1=172.30.0.11
FAKE2=172.30.0.12
SINK_PORT=4443
SCN=$ENVDEV_DIR/data/scenarios

D() { sudo -n docker "$@"; }
say() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { say "FAIL: $*"; exit 1; }
ok() { say "OK: $*"; }

# wait_log <container> <seconds> <grep -E pattern> [since]: succeed when the pattern shows up
wait_log() {
  local c=$1 pat=$3 since=${4:-$STARTED} end=$(( $(date +%s) + $2 ))
  while [ "$(date +%s)" -lt "$end" ]; do
    D logs --since "$since" "$c" 2>&1 | grep -qE "$pat" && return 0
    sleep 10
  done
  return 1
}
count_log() { D logs --since "${3:-$STARTED}" "$1" 2>&1 | grep -cE "$2" || true; }
restarts() { D inspect "$1" --format '{{.RestartCount}}'; }
status() { curl -s "localhost:8081/patrol/patrol_status?camera_ip=$1"; }
mark() { STARTED=$(date +%Y-%m-%dT%H:%M:%S); }  # docker --since reads local time

cams() { python3 -c "import json;print(' '.join(json.load(open('$ENGINE_DIR/data/credentials.real.json'))))"; }
set_env() { grep -q "^$1=" "$ENGINE_DIR/.env" && sed -i -E "s/^$1=.*/$1=$2/" "$ENGINE_DIR/.env" || echo "$1=$2" >> "$ENGINE_DIR/.env"; }
stack_up() { (cd "$ENGINE_DIR" && D compose up -d --force-recreate >/dev/null 2>&1); mark; sleep 20; }

use_real() { cp "$ENGINE_DIR/data/credentials.real.json" "$ENGINE_DIR/data/credentials.json"; D stop fakecam-1 fakecam-2 >/dev/null 2>&1 || true; }
use_fake() { cp "$ENGINE_DIR/data/credentials.fake.json" "$ENGINE_DIR/data/credentials.json"; }

# fakecam <1|2> <scenario>: (re)start one fake Reolink camera serving that scenario
fakecam() {
  local n=$1 ip name
  [ "$n" = 1 ] && ip=$FAKE1 || ip=$FAKE2
  name=$(python3 -c "import json;c=json.load(open('$ENGINE_DIR/data/credentials.fake.json'));print(c['$ip']['name'])")
  D rm -f "fakecam-$n" >/dev/null 2>&1 || true
  set -a; . "$ENGINE_DIR/.env"; set +a
  D run -d --name "fakecam-$n" --network $FAKE_NET --ip "$ip" -e CAMERA="$name" -e SCENARIO="$2" \
    -e CAM_USER="$CAM_USER" -e CAM_PWD="$CAM_PWD" -v "$SCN:/scenarios:ro" pyronear/fake-camera:local >/dev/null
}

# sink <ip...>: redirect each camera's HTTPS to a local listener that accepts and never answers
sink_on() {
  python3 -c "
import socket; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
s.bind(('0.0.0.0',$SINK_PORT)); s.listen(100); held=[]
while True: held.append(s.accept()[0])" >/dev/null 2>&1 &
  echo $! > /tmp/sink.pid
  for _ in 1 2 3 4 5 6 7 8 9 10; do ss -ltn | grep -q ":$SINK_PORT " && break; sleep 0.5; done
  ss -ltn | grep -q ":$SINK_PORT " || die "sink listener did not start"
  local me; me=$(ip -4 route get 1.1.1.1 | awk '{print $7; exit}')
  for ip in "$@"; do sudo -n iptables -t nat -I OUTPUT -d "$ip" -p tcp --dport 443 -m comment --comment pyro-robustness-sink -j DNAT --to-destination "$me:$SINK_PORT"; done
  echo "$*" > /tmp/sink.ips
  # Probe: a connection to the camera must now hang (curl rc 28), not fail or answer
  for ip in "$@"; do
    local rc=0; curl -sk -m 3 -o /dev/null "https://$ip/" || rc=$?
    [ "$rc" = 28 ] || die "sink not effective for $ip (curl rc=$rc)"
  done
}
sink_off() {
  [ -f /tmp/sink.ips ] || return 0
  local me; me=$(ip -4 route get 1.1.1.1 | awk '{print $7; exit}')
  for ip in $(cat /tmp/sink.ips); do sudo -n iptables -t nat -D OUTPUT -d "$ip" -p tcp --dport 443 -m comment --comment pyro-robustness-sink -j DNAT --to-destination "$me:$SINK_PORT" 2>/dev/null || true; done
  kill "$(cat /tmp/sink.pid)" 2>/dev/null || true
  rm -f /tmp/sink.ips /tmp/sink.pid
}
trap sink_off EXIT INT TERM

# ---------------------------------------------------------------- setup
setup() {
  say "branch test/$TAG = develop + $BRANCHES"
  cd "$ENGINE_DIR"
  git config user.email >/dev/null || git config user.email "test@pyronear.org"
  git config user.name >/dev/null || git config user.name "pi-test"
  git stash -q 2>/dev/null || true
  git fetch -q origin
  git checkout -q -B "test/$TAG" origin/develop
  for b in $BRANCHES; do git merge -q --no-edit "origin/$b" || die "conflict merging $b"; done
  say "pyro-engine at $(git rev-parse --short HEAD)"
  set_env PYRO_ENGINE_VERSION "$TAG"
  set_env ENABLE_STUCK_DETECTOR true
  set_env ALLOW_STILL_CAMERA false
  [ -f data/credentials.real.json ] || cp data/credentials.json data/credentials.real.json

  say "building images (develop's compose build context is broken, build like the Makefile)"
  D build -q pyro_camera_api -t "pyronear/pyro-camera-api:$TAG"
  D build -q . -t "pyronear/pyro-engine:$TAG"

  say "fake Reolink cameras (pyro-envdev#65)"
  [ -d "$ENVDEV_DIR" ] || git clone -q --depth 1 -b feat/fake-reolink-camera https://github.com/pyronear/pyro-envdev.git "$ENVDEV_DIR"
  cd "$ENVDEV_DIR"
  [ -d data/scenarios/never-smoke/nemours-02 ] || {
    curl -fsSL https://github.com/pyronear/pyro-envdev/releases/download/scenarios/never-smoke.zip -o /tmp/ns.zip
    unzip -oq /tmp/ns.zip -d data/scenarios; rm /tmp/ns.zip; }
  D build -q --build-context scenarios=data/scenarios -f containers/fake_camera/Dockerfile -t pyronear/fake-camera:local containers/fake_camera/
  D network inspect $FAKE_NET >/dev/null 2>&1 || D network create --subnet 172.30.0.0/24 $FAKE_NET >/dev/null

  say "scenarios: day (one colour frame), night (same frame in grayscale = IR), noisy (40 variants of one view)"
  read -r REAL1 REAL2 <<<"$(cams)"
  python3 - "$ENGINE_DIR/data/credentials.real.json" "$ENGINE_DIR/data/credentials.fake.json" "$REAL1" "$REAL2" "$FAKE1" "$FAKE2" <<'EOF'
import json, sys
src, dst, r1, r2, f1, f2 = sys.argv[1:]
c = json.load(open(src)); out = {}
for old, new in ((r1, f1), (r2, f2)):
    d = dict(c[old]); d["adapter"] = "reolink"; out[new] = d
json.dump(out, open(dst, "w"), indent=2)
EOF
  D run --rm -v "$SCN:/s" -v "$ENGINE_DIR/data/credentials.fake.json:/creds.json:ro" "pyronear/pyro-camera-api:$TAG" python - <<'EOF'
import json, pathlib
import numpy as np
from PIL import Image
creds = json.load(open("/creds.json"))
src = sorted(pathlib.Path("/s/never-smoke").glob("*/000.jpg"))
poses = {str(p): i * 90.0 for i, p in enumerate(next(iter(creds.values()))["poses"])}
rng = np.random.default_rng(0)
for scn in ("day", "night", "noisy"):
    d = pathlib.Path(f"/s/pi-{scn}"); d.mkdir(exist_ok=True)
    d.joinpath("scenario.json").write_text(json.dumps({"description": scn, "cameras": {c["name"]: {"poses": poses} for c in creds.values()}}))
    for cam, frame in zip(creds.values(), src):
        out = d / cam["name"]; out.mkdir(exist_ok=True)
        img = Image.open(frame).convert("RGB")
        if scn == "day":
            img.save(out / "000.jpg", quality=90)
        elif scn == "night":
            img.convert("L").save(out / "000.jpg", quality=90)
        else:
            base = np.asarray(img, dtype=np.int16)
            for i in range(40):
                Image.fromarray(np.clip(base + rng.integers(-6, 7, base.shape, dtype=np.int16), 0, 255).astype(np.uint8)).save(out / f"{i:03d}.jpg", quality=90)
print("scenarios written")
EOF
  sudo -n chown -R "$USER" "$SCN"
  ok "setup done, images tagged $TAG"
}

# ---------------------------------------------------------------- tests
test_419() {
  say "419: freeze the engine, backdate engine.log, expect a restart"
  use_real; stack_up
  local before; before=$(restarts engine); mark
  D top engine -o pid,comm | awk '/python|tee/ {print $1}' | xargs sudo -n kill -STOP
  D exec engine touch -d "2 hours ago" engine.log
  local end=$(( $(date +%s) + 120 ))
  while [ "$(date +%s)" -lt "$end" ]; do [ "$(restarts engine)" -gt "$before" ] && break; sleep 5; done
  [ "$(restarts engine)" -gt "$before" ] || die "engine not restarted within 2 min"
  wait_log engine 60 "verified in API" || die "engine did not come back"
  ok "419 engine killed by the healthcheck and restarted"
}

test_458_timeout() {
  say "458: black-hole the first camera's HTTPS, expect 'Read timed out (read timeout=10)'"
  use_real; stack_up
  read -r REAL1 _ <<<"$(cams)"
  sink_on "$REAL1"; mark
  wait_log pyro-camera-api 180 "\[$REAL1\].*Read timed out.*read timeout=10" || die "no 10 s timeout seen"
  sink_off
  ok "458 Reolink call timed out after 10 s instead of hanging"
}

test_458_health() {
  say "458: freeze the camera API, expect the healthcheck to restart it"
  use_real; stack_up
  local before; before=$(restarts pyro-camera-api)
  D top pyro-camera-api -o pid,comm | awk '/uvicorn|python/ {print $1}' | xargs sudo -n kill -STOP
  local end=$(( $(date +%s) + 180 ))
  while [ "$(date +%s)" -lt "$end" ]; do [ "$(restarts pyro-camera-api)" -gt "$before" ] && break; sleep 5; done
  [ "$(restarts pyro-camera-api)" -gt "$before" ] || die "camera API not restarted within 3 min"
  ok "458 camera API killed by the healthcheck and restarted"
}

test_459() {
  say "459: camera 1 grayscale (IR), camera 2 colour: night frames skipped, site awake"
  fakecam 1 pi-night; fakecam 2 pi-day; use_fake; stack_up
  wait_log engine 240 "Night frame for ${FAKE1}_" || die "no night frame seen on camera 1"
  wait_log engine 120 "Frame identical to the previous one for ${FAKE2}_" || die "identical frame not skipped on camera 2"
  [ "$(count_log engine 'Nighttime detected')" = 0 ] || die "site went to sleep with a day camera"
  ok "459 phase 1: night per frame, identical frames skipped, no sleep"

  say "459: stop camera 2 so it answers 204 after 5 min: one night frame + one missing must not sleep"
  D stop fakecam-2 >/dev/null; mark
  sleep 480
  [ "$(count_log engine 'Nighttime detected')" = 0 ] || die "site went to sleep on night + 204"
  curl -s -o /dev/null -w '%{http_code}' "localhost:8081/cameras/latest_image?camera_ip=$FAKE2&pose=$(python3 -c "import json;print(json.load(open('$ENGINE_DIR/data/credentials.json'))['$FAKE2']['poses'][0])")" | grep -q 204 || die "camera 2 not in 204"
  ok "459 phase 2: 204 never proves night"

  say "459: both cameras grayscale: patrols stopped, site sleeps"
  fakecam 2 pi-night; mark
  wait_log engine 240 "Nighttime detected by every camera" || die "site did not sleep with every camera at night"
  [ "$(count_log engine 'Stopped patrol for camera')" -ge 1 ] || die "patrols not stopped"
  ok "459 phase 3: every camera at night, sleep"
}

test_461_silent() {
  say "461: black-hole both cameras: no_fresh_image -> API reboot attempt, budget kept across a restart"
  use_real; sudo -n rm -f "$ENGINE_DIR/data/camera_recovery.json"; stack_up
  read -r REAL1 REAL2 <<<"$(cams)"
  sink_on "$REAL1" "$REAL2"; mark
  wait_log pyro-camera-api 1000 "\[$REAL1\] Rebooting camera, no_fresh_image" || die "no reboot attempt within 16 min"
  sleep 15
  [ "$(count_log pyro-camera-api 'Reboot raised.*password=')" = 0 ] || die "camera password leaked in the log"
  status "$REAL1" | grep -q '"reboot_attempts_24h":1' || die "status does not show 1 attempt"
  grep -q "$REAL1" "$ENGINE_DIR/data/camera_recovery.json" || die "attempt not saved on disk"
  D restart pyro-camera-api >/dev/null; sleep 25
  status "$REAL1" | grep -q '"reboot_attempts_24h":1' || die "attempt lost after a container restart"
  sink_off
  ok "461 silent camera: reboot attempted, no password in logs, budget survives a restart"
}

test_461_frozen() {
  say "461: camera 1 frozen (same pixels), camera 2 not moving (fresh frames, same view), ALLOW_STILL_CAMERA=false"
  fakecam 1 pi-day; fakecam 2 pi-noisy; use_fake; sudo -n rm -f "$ENGINE_DIR/data/camera_recovery.json"; stack_up
  wait_log pyro-camera-api 1000 "\[$FAKE1\] Rebooting camera, frozen" || die "camera 1 not rebooted for frozen within 16 min"
  wait_log pyro-camera-api 60 "\[$FAKE2\] Rebooting camera, not_moving" || die "camera 2 not rebooted for not_moving"
  [ "$(count_log pyro-camera-api 'Reboot command rejected')" = 0 ] || die "fake camera rejected the reboot"
  ok "461 frozen and not_moving detected, reboot sent"

  say "461: cooldown: 'budget spent' once, then a second reboot 30 min after the first"
  wait_log pyro-camera-api 1000 "\[$FAKE1\].*reboot budget spent" || die "no budget message at the next hit 2/2"
  sleep 1000
  [ "$(count_log pyro-camera-api "\[$FAKE1\].*reboot budget spent")" = 1 ] || die "budget message logged more than once"
  status "$FAKE1" | grep -q '"reboot_attempts_24h":2' || die "second attempt not made after the cooldown"
  ok "461 cooldown: one budget line, second reboot after 30 min, 2 attempts on disk"
}

# ---------------------------------------------------------------- main
STARTED=$(date +%Y-%m-%dT%H:%M:%S)
case "${1:-}" in
  setup) setup ;;
  419) test_419 ;;
  458-timeout) test_458_timeout ;;
  458-health) test_458_health ;;
  459) test_459 ;;
  461-silent) test_461_silent ;;
  461-frozen) test_461_frozen ;;
  all) test_419; test_458_timeout; test_458_health; test_459; test_461_silent; test_461_frozen; use_real; stack_up; ok "all scenarios passed" ;;
  real) use_real; stack_up; ok "back on the real cameras" ;;
  *) sed -n '2,20p' "$0"; exit 1 ;;
esac
