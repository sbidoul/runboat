import {LitElement, html} from 'https://unpkg.com/lit@2.0.2?module';

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

    render() {
        return html`
        <div>
            <p>${this.build.name}</p>
            <p>
                ${this.build.repo}
                ${this.build.pr?
                    html`PR <a href="${this.build.repo_link}">${this.build.pr}</a> to`:""
                }
                <a href="${this.build.repo_link}">${this.build.target_branch}</a>
                ${this.build.git_commit?
                    html`(<a href="${this.build.repo_commit_link}">${this.build.git_commit.substring(0, 8)}</a>)`:""
                }
            </p>
            <p>Status: ${this.build.status}</p>
            <p>Logs:
                <a href="/api/v1/builds/${this.build.name}/init-log">init log</a>
                ${this.build.status == "started"?
                    html`| <a href="/api/v1/builds/${this.build.name}/log">log</a>`:""
                }
            </p>
            <p>
                <button @click="${this.stopHandler}" ?disabled="${this.build.status != "started"}">stop</button>
                <button @click="${this.startHandler}" ?disabled="${this.build.status != "stopped"}">start</button>
                ${this.build.status == "started"?
                   html`<a href="${this.build.deploy_link}">=&gt; live</a>`:""
                }
            </p>
        <div>
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
