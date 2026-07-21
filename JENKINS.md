# Jenkins pipeline — documentary channel daily auto-upload

The [Jenkinsfile](Jenkinsfile) builds the Docker image, injects your secrets from
Jenkins credentials, and deploys the daily-upload container with `docker compose`.

```
Checkout → Validate → Build image → Stage runtime dir + secrets → Deploy → Smoke check → (optional) Run once
```

## Default architecture (what the Jenkinsfile assumes)

- **Jenkins agent runs on the same host that will run the container** (e.g. the EC2
  box), and that host has Docker. This is the simplest setup — no registry, no SSH.
- The container runs from a **stable directory** `APP_DIR` (default `/opt/documentary`),
  *not* the Jenkins workspace — because `docker-compose` bind-mounts `.env` and the output
  folders, and those host paths must survive after the build finishes.
- Secrets come from **Jenkins "Secret file" credentials**, never from git.

If your Jenkins is on a *different* machine than the deploy target, see
[Remote deploy](#remote-deploy-ecr--ssh) below.

## One-time setup

### 1. Agent requirements
On the Jenkins agent (the EC2 host):
```bash
sudo dnf install -y docker git            # or apt-get on Ubuntu
sudo systemctl enable --now docker
sudo usermod -aG docker jenkins           # the user the agent runs as
sudo mkdir -p /opt/documentary && sudo chown jenkins /opt/documentary
```
Install the Jenkins **Docker Pipeline** and **Credentials Binding** plugins.

### 2. Upload secrets as credentials
**Manage Jenkins → Credentials → (global) → Add Credentials**, kind = *Secret file*:

| Credential ID | Upload this file |
|---|---|
| `documentary-root-env` | your `./.env` (Anthropic + YouTube client id/secret) |
| `documentary-env` | your `./documentary/.env` (channel refresh token + pipeline knobs) |

> Using the Google Sheet queue or Cloud TTS fallback? Add a third *Secret file*
> credential for the service-account JSON and a `withCredentials`/`cp` line to place it
> at the path `documentary/.env`'s `DOC_SERVICE_ACCOUNT_JSON` points to, plus a mount in
> `docker-compose.yml`. Both are optional (local mirror + free Edge voice work without).

### 3. Create the pipeline job
**New Item → Pipeline** (or *Multibranch Pipeline*) → *Pipeline script from SCM* →
point at this repo. Jenkins auto-detects `Jenkinsfile` at the root.

### 4. Run it
Click **Build with Parameters**. Leave `APP_DIR` default. First run builds the image
(a few minutes: apt + `npm ci` native compile + pip) and starts the scheduler.

Tick **RUN_ONCE_AFTER_DEPLOY** if you want it to produce + upload one episode right
after deploying (real quota, publishes publicly) as an end-to-end test.

## What "deployed" means

The container stays up (`restart: unless-stopped`) and fires
`scripts/cron-documentary.sh` at **08:00 in the container timezone** (`TZ=Asia/Kolkata`
= IST, set in `docker-compose.yml`). Each run: topic → Hindi script → deep-voice
narration → multi-image visuals → suspense music → 1080p render → public upload with
Hindi+English captions.

Watch it: `cd /opt/documentary && docker compose logs -f`.

## Auto-build on every push (already wired)

The Jenkinsfile declares `triggers { githubPush(); pollSCM('H/15 * * * *') }`, so once
the webhook is connected, **every push to the repo rebuilds the image and redeploys**.
The 15-min SCM poll is a fallback in case a webhook delivery is ever missed.

To connect the webhook:

1. Install the **GitHub** plugin in Jenkins (Manage Jenkins → Plugins).
2. On the pipeline job: **Configure → Build Triggers → tick "GitHub hook trigger for
   GITScm polling"** (this is what `githubPush()` binds to).
3. In the GitHub repo: **Settings → Webhooks → Add webhook**
   - **Payload URL:** `https://<your-jenkins-host>/github-webhook/`  (note the trailing slash)
   - **Content type:** `application/json`
   - **Events:** *Just the push event*
4. Push a commit → GitHub pings Jenkins → the pipeline runs automatically. Verify under
   the webhook's **Recent Deliveries** (expect a `200`).

> Jenkins must be reachable from GitHub. On a private EC2, either expose Jenkins behind
> an HTTPS reverse proxy / load balancer, or rely on the `pollSCM` fallback alone
> (no inbound webhook needed).

## Remote deploy (ECR + SSH)

If Jenkins is *not* on the deploy host, change the strategy to build-push-pull:

1. **Build & push** to Amazon ECR in the pipeline:
   ```groovy
   sh 'aws ecr get-login-password | docker login --username AWS --password-stdin $ECR_REPO'
   sh 'docker build -t $ECR_REPO/$IMAGE:$TAG . && docker push $ECR_REPO/$IMAGE:$TAG'
   ```
   (Use an EC2 instance role or `amazon-ecr` Jenkins credentials for auth.)
2. Point `docker-compose.yml`'s `image:` at `$ECR_REPO/$IMAGE:latest` and drop `build:`.
3. **Deploy over SSH** with the *SSH Agent* plugin:
   ```groovy
   sshagent(['ec2-deploy-key']) {
     sh 'ssh ec2-user@$HOST "cd /opt/documentary && docker compose pull && docker compose up -d"'
   }
   ```
   Keep the `.env` files on the EC2 host under `/opt/documentary` (or fetch from AWS
   Secrets Manager on the box) so they aren't shipped through Jenkins each deploy.

Tell me your topology (same-host vs remote, registry vs none) and I'll tailor the
Jenkinsfile to exactly that.
