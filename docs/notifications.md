# Job notifications

Each account can add notification hooks under **Notifications** in the user menu (`/ui/notifications/`). The worker3 process sends them when a job it runs changes status. The web app does not send these messages; the machine running `python -m worker3` must be able to reach the service.

Apply the database migration after pulling this change:

```bash
python manage.py migrate
```

## Events

| Event | When |
| --- | --- |
| Started | The worker claims the job and begins running it. Off unless you check it. |
| Finished | Every step completed. |
| Failed | A step failed, inputs were missing, the protocol template could not be expanded, or the worker restarted while the job was still marked running. |
| Interrupted | The job was terminated. |

A hook can listen for any combination. **Test** sends one sample message even if Finished is unchecked, so you can confirm the destination before relying on it.

## Services

| Service | What to paste |
| --- | --- |
| Discord | Channel → Integrations → Webhooks → copy the webhook URL. |
| Telegram | Bot token from @BotFather, and the chat id (message [@userinfobot](https://t.me/userinfobot), or a negative id for a group). |
| Slack | Incoming webhook URL (`hooks.slack.com`). |
| Microsoft Teams | Incoming webhook URL. Classic connectors accept the MessageCard body BioQueue sends. |
| Mattermost | Incoming webhook URL. |
| ntfy | Topic URL such as `https://ntfy.sh/your-private-topic`, plus an access token if the topic is protected. |
| Gotify | Server URL and an application token. |
| Pushover | User key and application API token. |
| Email | Recipient address. SMTP comes from the hook, or from `[mail]` in `config/custom.conf` when the hook leaves SMTP blank. |
| Generic webhook | Any `http` or `https` URL. BioQueue POSTs JSON. |

Secrets are stored in the database for that account. The worker log records the hook id and the HTTP status, not the token. Webhook URLs are not shown again on the list; leave a secret field blank when editing to keep the saved value.

## Generic webhook body

```json
{
  "event": "finished",
  "job_id": 12,
  "job_name": "align",
  "protocol": "RNA-seq",
  "workspace": "RNA-seq 2026",
  "message": "BioQueue: align (#12) finished.\nProtocol: RNA-seq\nWorkspace: RNA-seq 2026"
}
```

If you set a signing secret, the request includes:

```text
X-BioQueue-Signature: sha256=<hmac-sha256 of the raw body>
```

The worker does not follow redirects.

## Email

`config/custom.conf`:

```ini
[mail]
sender = bioqueue@example.com
mail_host = smtp.example.com
mail_port = 587
mail_user = bioqueue@example.com
mail_password = secret
```

Port 587 uses STARTTLS unless the hook sets security to None. Port 465 uses SSL. A hook can override the host, port, user, password, and From address.

## Limits

Thirty hooks per account. Delivery is best-effort: a timeout or HTTP error is written to the worker log and does not change the job. Requests time out after 8 seconds.
