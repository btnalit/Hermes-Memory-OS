# Memory-OS Monitor Dashboard

Read-only static frontend for the Hermes Memory-OS monitoring handoff.

The page renders `window.MOS` with no approve/apply/send controls. By default it
uses `assets/sample-data.js` so the dashboard can be opened immediately. To
render a real profile snapshot:

```bash
python scripts/memory_os_monitor_dashboard_snapshot.py \
  --hermes-home /root/.hermes \
  --profile main \
  --output monitor_dashboard/snapshot.generated.js
```

Then serve the dashboard on the monitoring frontend port:

```bash
python scripts/serve_memory_os_monitor_dashboard.py --host 0.0.0.0 --port 3693
```

For a systemd system service with boot autostart:

```bash
sudo python scripts/install_memory_os_monitor_dashboard_service.py \
  --repo-root /opt/Hermes-Memory-OS \
  --hermes-home /root/.hermes \
  --profile main \
  --host 0.0.0.0 \
  --port 3693 \
  --python-bin /usr/bin/python3 \
  --enable
```

The open-source frontend contract is `0.0.0.0:3693`. `snapshot.generated.js` is
intentionally git-ignored because it may contain live operational evidence.
