import {LitElement, html, css} from 'https://unpkg.com/lit@2.1.2?module';
import 'https://unpkg.com/@github/time-elements@latest?module';

class RunboatBuildElement extends LitElement {
    static get properties() {
        return {
            build: {}
        }
    }

    constructor() {
        super();
        this.build = {};
    }

    undeployed() {
        this.build = {...this.build, status: null};
    }

    static styles = css`
        .build-card {
            width: 16em;
            padding: 0.5em;
            border-radius: 0.5em;
            background-color: lightgray;
        }
        .build-name {
            font-size: x-small;
        }
        .build-status-stopped {
            background-color: paleturquoise;
        }
        .build-status-started {
            background-color: palegreen;
        }
        .build-status-failed {
            background-color: lightcoral;
        }
        time-ago {
            color: gray;
            white-space: nowrap;
        }
        p {
            margin-top: 0.5em;
            margin-bottom: 0.5em;
        }
    `;

    render() {
        if (!this.build.name) {
            return html`<div class="build-card"><p>Build not found...</p></div>`;
        }
        return html`
        <div class="build-card build-status-${this.build.status}">
            <p class="build-name">${this.build.name}</p>
            <p>
                <a href="${this.build.repo_target_branch_link}">${this.build.commit_info?.repo} ${this.build.commit_info?.target_branch}</a>
                ${this.build.commit_info?.pr?
                    html`PR <a href="${this.build.repo_pr_link}">${this.build.commit_info?.pr}</a>`:""
                }
                ${this.build.commit_info?.git_commit?
                    html`(<a href="${this.build.repo_commit_link}">${this.build.commit_info?.git_commit.substring(0, 8)}</a>)`:""
                }
                <time-ago datetime="${this.build.created}"></time-ago>
            </p>
            <p>
                ${this.build.status || "undeployed"}
                ${this.build.status?
                    html`⦙ 🗒 <a href="/api/v1/builds/${this.build.name}/init-log">init log</a>`:""
                }
                ${this.build.status == "started"?
                    html`⦙ 🗒 <a href="/api/v1/builds/${this.build.name}/log">log</a>`:""
                }
                ${this.build.status == "started"?
                   html`⦙ 🚪 <a href="${this.build.deploy_link}">live</a>`:""
                }
            </p>
            <p>
                <button @click="${this.startHandler}" ?disabled="${this.build.status != "stopped" || this.build.status == RunboatBuildElement.clickedStatus}">start</button>
                <button @click="${this.stopHandler}" ?disabled="${this.build.status != "started" || this.build.status == RunboatBuildElement.clickedStatus}">stop</button>
                <button @click="${this.resetHandler}" ?disabled="${this.build.status == RunboatBuildElement.clickedStatus}">reset</button>
            </p>
        </div>
        `;
    }

    startHandler(e) {
        this.actionHandler("start");
    }

    stopHandler(e) {
        this.actionHandler("stop");
    }

    resetHandler(e) {
        this.actionHandler("reset");
    }

    static clickedStatus = "⏳";

    actionHandler(action) {
        this.build.status = RunboatBuildElement.clickedStatus;
        this.requestUpdate();
        fetch(`/api/v1/builds/${this.build.name}/${action}`, {method: 'POST'});
    }
}

export {RunboatBuildElement};
