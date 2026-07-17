// Jenkins pipeline for the Giggle Grove daily kids-rhyme auto-upload.
//
// What it does: validate -> build the Docker image -> inject secrets from Jenkins
// credentials into a STABLE runtime dir (not the ephemeral workspace) -> deploy with
// docker compose -> smoke check.
//
// Why a stable APP_DIR: docker-compose bind-mounts ./.env and the output dirs from the
// compose file's directory. Those host paths must outlive the build, so we deploy from
// $APP_DIR (default /opt/giggle-grove), NOT the Jenkins workspace (which gets wiped).
//
// Prerequisites on the Jenkins AGENT (see JENKINS.md):
//   - docker + docker compose plugin, and the agent user in the `docker` group
//   - two "Secret file" credentials uploaded to Jenkins:
//       kids-root-env      -> your ./.env
//       kids-history-env   -> your ./hindi-history/.env
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
    string(name: 'APP_DIR', defaultValue: '/opt/giggle-grove',
           description: 'Stable host dir the container runs from (holds secrets + volumes).')
    booleanParam(name: 'RUN_ONCE_AFTER_DEPLOY', defaultValue: false,
           description: 'After deploy, immediately generate + upload ONE episode (uses real quota, publishes publicly).')
  }

  environment {
    IMAGE = 'giggle-grove-rhyme'
    TAG   = "${env.BUILD_NUMBER}"
  }

  stages {
    stage('Checkout') {
      steps { checkout scm }
    }

    stage('Validate') {
      steps {
        sh '''
          set -eu
          echo "--- shell syntax ---"
          bash -n docker/entrypoint.sh
          bash -n scripts/cron-kids-rhyme.sh
          echo "--- node syntax ---"
          if command -v node >/dev/null 2>&1; then node --check kids_upload.mjs; else echo "(node not on agent; skipped)"; fi
          echo "--- python compile ---"
          if command -v python3 >/dev/null 2>&1; then python3 -m compileall -q hindi-history || true; else echo "(python3 not on agent; skipped)"; fi
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
          mkdir -p "$APP_DIR/hindi-history/data" "$APP_DIR/hindi-history/images" \
                   "$APP_DIR/hindi-history/renders" "$APP_DIR/hindi-history/audio" \
                   "$APP_DIR/hindi-history/logs" "$APP_DIR/logs"
          cp docker-compose.yml "$APP_DIR/docker-compose.yml"
        '''
        withCredentials([
          file(credentialsId: 'kids-root-env',    variable: 'ROOT_ENV'),
          file(credentialsId: 'kids-history-env', variable: 'HISTORY_ENV')
        ]) {
          sh '''
            set -eu
            install -m 600 "$ROOT_ENV"    "$APP_DIR/.env"
            install -m 600 "$HISTORY_ENV" "$APP_DIR/hindi-history/.env"
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
          docker compose ps --status running | grep -q giggle-grove-rhyme && echo "container running ✔"
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
          docker compose run --rm rhyme once
        '''
      }
    }
  }

  post {
    always {
      // Never leave secret copies in the (persisted) workspace.
      sh 'rm -f .env hindi-history/.env || true'
    }
    success { echo "Deployed $IMAGE:$TAG. Daily job fires 08:00 (container TZ). APP_DIR=${params.APP_DIR}" }
    failure { echo 'Pipeline failed — see stage logs above.' }
  }
}
