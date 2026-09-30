



set -euo pipefail

HB_VERSION="1.0.0"
HB_BASE_URL="${HB_BASE_URL:-http://localhost:5000}"
HB_TOKEN="${HB_TOKEN:-}"
HB_JOB="${HB_JOB:-}"
HB_NO_LOG="${HB_NO_LOG:-false}"
HB_START_TIMEOUT="${HB_START_TIMEOUT:-5}"
HB_RETRY_TIMEOUT="${HB_RETRY_TIMEOUT:-90}"

usage() {
    cat <<EOF
Heartbeat Monitor CLI Wrapper v$HB_VERSION

Usage:
    hb run --job <job_name> -- <command> [args...]
    hb version
    hb help

Environment Variables:
    HB_BASE_URL     Base URL of Heartbeat Monitor (default: http://localhost:5000)
    HB_TOKEN        Job token (can also be set via config file)
    HB_JOB          Job name (alternative to token)
    HB_NO_LOG       Don't send command output in final request (default: false)

Config File:
    ~/.config/heartbeat-monitor/config.json
    {
        "base_url": "http://localhost:5000",
        "jobs": {
            "daily-backup": "your-token-here"
        }
    }

Examples:
    
    HB_TOKEN=abc123 hb run --job backup -- /backup.sh

    
    hb run --job daily-backup -- /backup.sh

    
    HB_BASE_URL=http://monitor.example.com hb run --job backup -- /backup.sh

The wrapper will:
1. Send "started" heartbeat before running the command
2. Execute the command
3. Send "success" or "failed" heartbeat after completion with exit code and output

Exit codes:
    0           Command succeeded
    1-125       Command failed (exit code from command)
    126         Command found but not executable
    127         Command not found
    128+N       Command terminated by signal N
    2           Configuration error (missing token, no command, etc.)
EOF
}

version() {
    echo "hb version $HB_VERSION"
}

load_config() {
    local config_file="${XDG_CONFIG_HOME:-$HOME/.config}/heartbeat-monitor/config.json"
    if [[ -f "$config_file" ]]; then
        if command -v jq >/dev/null 2>&1; then
            HB_BASE_URL=$(jq -r '.base_url // empty' "$config_file" 2>/dev/null || echo "$HB_BASE_URL")
            if [[ -n "$HB_JOB" && -z "$HB_TOKEN" ]]; then
                HB_TOKEN=$(jq -r ".jobs[\"$HB_JOB\"] // empty" "$config_file" 2>/dev/null || echo "")
            fi
        fi
    fi
}

send_heartbeat() {
    local token="$1"
    local status="$2"
    local exit_code="${3:-}"
    local output="${4:-}"
    local duration_ms="${5:-}"
    
    local url="${HB_BASE_URL%/}/api/heartbeat/$token"
    local payload
    
    if [[ "$HB_NO_LOG" == "true" ]]; then
        output=""
    fi
    
    payload=$(jq -n \
        --arg status "$status" \
        --argjson exit_code "${exit_code:-null}" \
        --arg output "$output" \
        --argjson duration_ms "${duration_ms:-null}" \
        '{status: $status, exit_code: $exit_code, output: $output, duration_ms: $duration_ms}')
    
    curl -sSf --max-time "$HB_RETRY_TIMEOUT" \
        -H "Content-Type: application/json" \
        -d "$payload" \
        "$url" >/dev/null
}

run_command() {
    local cmd=("$@")
    local start_time end_time duration_ms exit_code output
    
    
    send_heartbeat "$HB_TOKEN" "started" || true
    
    start_time=$(date +%s%3N)
    
    
    if [[ "$HB_NO_LOG" == "true" ]]; then
        "${cmd[@]}"
        exit_code=$?
        output=""
    else
        output=$("${cmd[@]}" 2>&1)
        exit_code=$?
    fi
    
    end_time=$(date +%s%3N)
    duration_ms=$((end_time - start_time))
    
    
    if [[ ${
        output="...${output: -102400}"
    fi
    
    
    local hb_status="success"
    if [[ $exit_code -ne 0 ]]; then
        hb_status="failed"
    fi
    
    
    local retries=0
    local max_retries=5
    local backoff=1
    
    while [[ $retries -lt $max_retries ]]; do
        if send_heartbeat "$HB_TOKEN" "$hb_status" "$exit_code" "$output" "$duration_ms"; then
            break
        fi
        retries=$((retries + 1))
        if [[ $retries -lt $max_retries ]]; then
            sleep $backoff
            backoff=$((backoff * 2))
            if [[ $backoff -gt 30 ]]; then
                backoff=30
            fi
        fi
    done
    
    return $exit_code
}

main() {
    load_config
    
    case "${1:-}" in
        version|--version|-v)
            version
            return 0
            ;;
        help|--help|-h)
            usage
            return 0
            ;;
        run)
            shift
            ;;
        *)
            usage
            return 2
            ;;
    esac
    
    
    local job_name=""
    local token=""
    local cmd_start=0
    
    while [[ $
        case "$1" in
            --job)
                job_name="$2"
                shift 2
                ;;
            --token)
                token="$2"
                shift 2
                ;;
            --)
                shift
                cmd_start=1
                break
                ;;
            *)
                if [[ $cmd_start -eq 0 ]]; then
                    echo "Error: Unknown option: $1" >&2
                    usage
                    return 2
                fi
                break
                ;;
        esac
    done
    
    if [[ $cmd_start -eq 0 ]]; then
        echo "Error: Missing '--' separator before command" >&2
        usage
        return 2
    fi
    
    if [[ $
        echo "Error: No command provided" >&2
        usage
        return 2
    fi
    
    
    if [[ -n "$token" ]]; then
        HB_TOKEN="$token"
    elif [[ -n "$job_name" && -z "$HB_TOKEN" ]]; then
        
        load_config
        if [[ -z "$HB_TOKEN" ]]; then
            echo "Error: No token provided for job '$job_name'. Set HB_TOKEN or use --token, or configure in ~/.config/heartbeat-monitor/config.json" >&2
            return 2
        fi
    fi
    
    if [[ -z "$HB_TOKEN" ]]; then
        echo "Error: No token provided. Set HB_TOKEN, use --token, or configure job in config file" >&2
        return 2
    fi
    
    if [[ -z "$HB_BASE_URL" ]]; then
        echo "Error: HB_BASE_URL not set" >&2
        return 2
    fi
    
    run_command "$@"
}

main "$@"