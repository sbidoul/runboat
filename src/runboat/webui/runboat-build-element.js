import {LitElement, html, css} from 'https://unpkg.com/lit@2.0.2?module';

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

    static styles = css`
        .build-card {
            padding: 0.5em;
            width: 15em;
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
            background-color: palevioletred;
        }
        p {
            margin-top: 0.5em;
            margin-bottom: 0.5em;
        }
    `;

    render() {
        return html`
        <div class="build-card build-status-${this.build.status}">
            <p class="build-name">${this.build.name}</p>
            <p>
                ${this.build.repo}
                ${this.build.pr?
                    html`PR <a href="${this.build.repo_link}">${this.build.pr}</a> to`:""
                }
                <a href="${this.build.repo_link}">${this.build.target_branch}</a>
                <br>
                ${this.build.git_commit?
                    html`(<a href="${this.build.repo_commit_link}">${this.build.git_commit.substring(0, 8)}</a>)`:""
                }
            </p>
            <p>
                ${this.build.status}
                | <a href="/api/v1/builds/${this.build.name}/init-log">init log</a>
                ${this.build.status == "started"?
                    html`| <a href="/api/v1/builds/${this.build.name}/log">log</a>`:""
                }
                ${this.build.status == "started"?
                   html`| <a href="${this.build.deploy_link}">🚪 live</a>`:""
                }
            </p>
            <p>
                <button @click="${this.stopHandler}" ?disabled="${this.build.status != "started"}">stop</button>
                <button @click="${this.startHandler}" ?disabled="${this.build.status != "stopped"}">start</button>
            </p>
        </div>
        `;
    }

    startHandler(e) {
        fetch(`/api/v1/builds/${this.build.name}/start`, {method: 'POST'});
    }

    stopHandler(e) {
        fetch(`/api/v1/builds/${this.build.name}/stop`, {method: 'POST'});
    }
}

export {RunboatBuildElement};
