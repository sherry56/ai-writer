import { DurableObject } from "cloudflare:workers";

const STATE_OBJECT_KEY = "state/latest.tar.gz";
const CONTAINER_IMAGE_KEY = "container/restored-image";
const INTERNAL_TOKEN_HEADER = "x-ai-writer-internal-token";
const WRITE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const IDLE_TIMEOUT_MS = 10 * 60 * 1000;
const STATE_CHUNK_BYTES = 1_500_000;
const MAX_STATE_BYTES = 40 * 1024 * 1024;
const STARTUP_RETRY_COUNT = 40;
const STARTUP_RETRY_DELAY_MS = 1000;

export default {
	async fetch(request, env) {
		const url = new URL(request.url);
		if (url.pathname === "/_ops/seed-state" && request.method === "POST") {
			const token = env.STATE_SEED_TOKEN;
			if (!token || request.headers.get("authorization") !== `Bearer ${token}`) {
				return new Response("Not found", { status: 404 });
			}
			const length = Number(request.headers.get("content-length") || 0);
			if (length > MAX_STATE_BYTES) {
				return new Response("State archive is too large", { status: 413 });
			}
			const archive = await request.arrayBuffer();
			if (archive.byteLength > MAX_STATE_BYTES) {
				return new Response("State archive is too large", { status: 413 });
			}
			const id = env.AI_WRITER.idFromName("production");
			const seeded = await env.AI_WRITER.get(id).seedState(archive);
			return new Response(seeded ? "Initial state saved" : "Initial state already exists", {
				status: seeded ? 201 : 409,
				headers: { "Cache-Control": "no-store" },
			});
		}
		const id = env.AI_WRITER.idFromName("production");
		return env.AI_WRITER.get(id).fetch(request);
	},
};

export class AiWriterContainer extends DurableObject {
	constructor(ctx, env) {
		super(ctx, env);
		this.starting = null;
		this.writeQueue = Promise.resolve();
	}

	fetch(request) {
		if (!WRITE_METHODS.has(request.method)) {
			return this.handleRequest(request);
		}

		const current = this.writeQueue.then(
			() => this.handleRequest(request),
			() => this.handleRequest(request),
		);
		this.writeQueue = current.then(() => undefined, () => undefined);
		return current;
	}

	async handleRequest(request) {
		try {
			await this.ensureContainer();
			const response = await this.appFetcher().fetch(this.toContainerRequest(request));

			if (WRITE_METHODS.has(request.method)) {
				await this.saveState();
			}
			return response;
		} catch (error) {
			console.error("ai-writer request failed", error);
			return new Response("AI-writer is temporarily unavailable. Please retry shortly.", {
				status: 503,
				headers: { "Retry-After": "5", "Cache-Control": "no-store" },
			});
		}
	}

	async seedState(archive) {
		if (await this.ctx.storage.get(STATE_OBJECT_KEY)) {
			return false;
		}
		await this.storeState(archive);
		return true;
	}

	async ensureContainer() {
		if (this.starting) {
			await this.starting;
			return;
		}

		this.starting = this.startOrRestore();
		try {
			await this.starting;
		} finally {
			this.starting = null;
		}
	}

	async startOrRestore() {
		const container = this.ctx.container;
		const expectedImage = container.images.app;
		const current = await container.inspect();

		if (
			container.running &&
			current?.image === expectedImage &&
			(await this.ctx.storage.get(CONTAINER_IMAGE_KEY)) === expectedImage
		) {
			await container.setInactivityTimeout(IDLE_TIMEOUT_MS);
			return;
		}

		if (container.running && current?.image !== expectedImage) {
			// Preserve live data before replacing an older application image.
			await this.saveState();
			await container.destroy("Replacing AI-writer image");
		}
		const archive = await this.loadState();
		if (!archive) {
			throw new Error("Initial state has not been uploaded");
		}

		const required = ["SESSION_SECRET", "MODELS_JSON", "INTERNAL_BACKUP_TOKEN"];
		for (const key of required) {
			if (!this.env[key]) {
				throw new Error(`Missing required Worker secret: ${key}`);
			}
		}

		const containerEnv = {
			SESSION_SECRET: this.env.SESSION_SECRET,
			SESSION_COOKIE_SECURE: "true",
			MODELS_JSON: this.env.MODELS_JSON,
			INTERNAL_BACKUP_TOKEN: this.env.INTERNAL_BACKUP_TOKEN,
			ADMIN_USER: this.env.ADMIN_USER || "sherry",
			FREE_LIMIT: this.env.FREE_LIMIT || "10",
			USAGE_TIMEZONE: this.env.USAGE_TIMEZONE || "Asia/Shanghai",
		};

		if (!container.running) {
			container.start({
				image: expectedImage,
				instance: "lite",
				enableInternet: true,
				env: containerEnv,
			});
			await container.setInactivityTimeout(IDLE_TIMEOUT_MS);
		}

		await this.waitForHealth();

		const restored = await this.internalRequest("/_internal/state/import", {
			method: "POST",
			body: archive,
			headers: { "Content-Type": "application/gzip" },
		});
		if (!restored.ok) {
			throw new Error(`AI-writer state restore failed (${restored.status})`);
		}
		await this.ctx.storage.put(CONTAINER_IMAGE_KEY, expectedImage);
	}

	async waitForHealth() {
		for (let attempt = 0; attempt < STARTUP_RETRY_COUNT; attempt += 1) {
			let response;
			try {
				response = await this.internalRequest("/_internal/state/health");
			} catch {
				response = undefined;
			}
			if (response?.ok) return;
			if (response && response.status !== 502 && response.status !== 503) {
				throw new Error(`AI-writer container readiness check failed (${response.status})`);
			}
			if (attempt + 1 < STARTUP_RETRY_COUNT) {
				await new Promise((resolve) => setTimeout(resolve, STARTUP_RETRY_DELAY_MS));
			}
		}
		throw new Error("AI-writer container did not become ready in 40 seconds");
	}

	async saveState() {
		const response = await this.internalRequest("/_internal/state/export");
		if (!response.ok || !response.body) {
			throw new Error(`AI-writer state export failed (${response.status})`);
		}
		await this.storeState(await response.arrayBuffer());
	}

	async loadState() {
		const manifest = await this.ctx.storage.get(STATE_OBJECT_KEY);
		if (!manifest || !Array.isArray(manifest.chunks)) return null;
		const parts = [];
		let length = 0;
		for (let index = 0; index < manifest.chunks; index += 1) {
			const part = await this.ctx.storage.get(`${STATE_OBJECT_KEY}:${manifest.version}:${index}`);
			if (!(part instanceof ArrayBuffer)) {
				throw new Error("AI-writer state backup is incomplete");
			}
			parts.push(new Uint8Array(part));
			length += part.byteLength;
		}
		if (length !== manifest.bytes || length > MAX_STATE_BYTES) {
			throw new Error("AI-writer state backup is invalid");
		}
		const archive = new Uint8Array(length);
		let offset = 0;
		for (const part of parts) {
			archive.set(part, offset);
			offset += part.byteLength;
		}
		return archive;
	}

	async storeState(input) {
		const archive = input instanceof ArrayBuffer ? new Uint8Array(input) : new Uint8Array(input);
		if (archive.byteLength > MAX_STATE_BYTES) {
			throw new Error("AI-writer state backup exceeds 40 MB");
		}
		const version = crypto.randomUUID();
		const chunks = Math.ceil(archive.byteLength / STATE_CHUNK_BYTES);
		for (let index = 0; index < chunks; index += 1) {
			const chunk = archive.slice(index * STATE_CHUNK_BYTES, (index + 1) * STATE_CHUNK_BYTES);
			await this.ctx.storage.put(`${STATE_OBJECT_KEY}:${version}:${index}`, chunk.buffer);
		}
		const previous = await this.ctx.storage.get(STATE_OBJECT_KEY);
		await this.ctx.storage.put(STATE_OBJECT_KEY, {
			version,
			chunks,
			bytes: archive.byteLength,
		});
		if (previous?.version && Array.isArray(previous.chunks)) {
			const oldKeys = Array.from(
				{ length: previous.chunks },
				(_, index) => `${STATE_OBJECT_KEY}:${previous.version}:${index}`,
			);
			if (oldKeys.length) await this.ctx.storage.delete(oldKeys);
		}
	}

	async internalRequest(path, init = {}) {
		const headers = new Headers(init.headers);
		headers.set(INTERNAL_TOKEN_HEADER, this.env.INTERNAL_BACKUP_TOKEN || "");
		const request = new Request(`http://container${path}`, { ...init, headers });
		return this.appFetcher().fetch(request);
	}

	appFetcher() {
		return this.ctx.container.getTcpPort(8000);
	}

	toContainerRequest(request) {
		const incoming = new URL(request.url);
		const target = new URL(`http://container${incoming.pathname}${incoming.search}`);
		return new Request(target, request);
	}
}
