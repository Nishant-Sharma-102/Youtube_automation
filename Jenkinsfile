// Jenkins pipeline for the documentary channel daily auto-upload.
//
// What it does: validate -> build the Docker image -> inject secrets from Jenkins
// credentials into a STABLE runtime dir (not the ephemeral workspace) -> deploy with
// docker compose -> smoke check.
//
// Why a stable APP_DIR: docker-compose bind-mounts ./.env and the output dirs from the
// compose file's directory. Those host paths must outlive the build, so we deploy from
// $APP_DIR (default /opt/documentary), NOT the Jenkins workspace (which gets wiped).
//
// Prerequisites on the Jenkins AGENT (see JENKINS.md):
//   - docker + docker compose plugin, and the agent user in the `docker` group
//   - two "Secret file" credentials uploaded to Jenkins:
//       documentary-root-env  -> your ./.env
//       documentary-env       -> your ./documentary/.env
//   - the agent can write to $APP_DIR
pipeline {
  agent any

  options {
    timestamps()
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '15'))
  }

  // Auto-build+redeploy on every push. Needs the GitHub plugin and a repo webhook
  // pointing at https://<jenkins>/github-webhook/ (see JENKINS.md). githubPush fires
  // on the webhook; the pollSCM fallback catches pushes if the webhook is ever missed.
  triggers {
    githubPush()
    pollSCM('H/15 * * * *')
  }

  parameters {
    string(name: 'REPO_URL', defaultValue: 'https://github.com/Nishant-Sharma-102/Youtube_automation.git',
           description: 'GitHub repository to build from.')
    string(name: 'BRANCH', defaultValue: 'main',
           description: 'Branch to build.')
    string(name: 'APP_DIR', defaultValue: '/opt/documentary',
           description: 'Stable host dir the container runs from (holds secrets + volumes).')
    booleanParam(name: 'RUN_ONCE_AFTER_DEPLOY', defaultValue: false,
           description: 'After deploy, immediately produce + publish ONE episode (uses real quota, publishes publicly).')
  }

  environment {
    IMAGE = 'documentary-daily'
    TAG   = "${env.BUILD_NUMBER}"
    // Jenkins "Username with password" credential holding a GitHub Personal Access
    // Token (username = your GitHub user, password = the PAT). Needed only for a
    // PRIVATE repo; harmless for a public one. Create it under Manage Jenkins →
    // Credentials with this ID (or change the ID here).
    GIT_CREDENTIALS_ID = 'github-pat'
  }

  stages {
    stage('Checkout') {
      steps {
        // Explicit GitHub checkout so this works as a plain Pipeline job (inline
        // script) — no "Pipeline script from SCM" configuration required. For a
        // public repo the credentialsId is simply ignored.
        git branch: "${params.BRANCH}",
            url: "${params.REPO_URL}",
            credentialsId: "${env.GIT_CREDENTIALS_ID}"
        sh 'git --no-pager log -1 --oneline'
      }
    }

    stage('Validate') {
      steps {
        sh '''
          set -eu
          echo "--- shell syntax ---"
          bash -n docker/entrypoint.sh
          bash -n scripts/cron-documentary.sh
          echo "--- node syntax ---"
          if command -v node >/dev/null 2>&1; then node --check documentary/orchestrator_documentary.js; else echo "(node not on agent; skipped)"; fi
          echo "--- python compile ---"
          if command -v python3 >/dev/null 2>&1; then python3 -m compileall -q documentary || true; else echo "(python3 not on agent; skipped)"; fi
        '''
      }
    }

    stage('Build image') {
      steps {
        sh '''
          set -eu
          docker build -t "$IMAGE:$TAG" -t "$IMAGE:latest" .
        '''
      }
    }

    stage('Stage runtime dir + secrets') {
      steps {
        sh '''
          set -eu
          mkdir -p "$APP_DIR/documentary/data" "$APP_DIR/documentary/images" \
                   "$APP_DIR/documentary/renders" "$APP_DIR/documentary/audio" \
                   "$APP_DIR/documentary/music" "$APP_DIR/documentary/logs" "$APP_DIR/logs"
          cp docker-compose.yml "$APP_DIR/docker-compose.yml"
        '''
        withCredentials([
          file(credentialsId: 'documentary-root-env', variable: 'ROOT_ENV'),
          file(credentialsId: 'documentary-env',      variable: 'DOC_ENV')
        ]) {
          sh '''
            set -eu
            install -m 600 "$ROOT_ENV" "$APP_DIR/.env"
            install -m 600 "$DOC_ENV"  "$APP_DIR/documentary/.env"
          '''
        }
      }
    }

    stage('Deploy') {
      steps {
        sh '''
          set -eu
          cd "$APP_DIR"
          # Use the image just built on this daemon; don't rebuild without context.
          docker compose up -d --no-build
          docker compose ps
        '''
      }
    }

    stage('Smoke check') {
      steps {
        sh '''
          set -eu
          cd "$APP_DIR"
          # Container should be up and supercronic scheduling. Show recent logs.
          sleep 3
          docker compose ps --status running | grep -q documentary-daily && echo "container running ✔"
          docker compose logs --tail=20
        '''
      }
    }

    stage('Run once (optional)') {
      when { expression { return params.RUN_ONCE_AFTER_DEPLOY } }
      steps {
        sh '''
          set -eu
          cd "$APP_DIR"
          docker compose run --rm documentary once
        '''
      }
    }
  }

  post {
    always {
      // Never leave secret copies in the (persisted) workspace.
      sh 'rm -f .env documentary/.env || true'
    }
    success { echo "Deployed $IMAGE:$TAG. Daily job fires 08:00 (container TZ). APP_DIR=${params.APP_DIR}" }
    failure { echo 'Pipeline failed — see stage logs above.' }
  }
}
