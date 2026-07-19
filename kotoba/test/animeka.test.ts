import { describe, it, expect, beforeEach } from "vitest";
import { MockEtzhayyim } from "@etzhayyim/sdk-mock";
import {
  defineWork,
  getWork,
  listWorks,
  registerEpisode,
  publishEpisode,
  announceEpisode,
  getEpisode,
  listEpisodes,
  coverage,
} from "../src/index.js";

const CREATOR = "did:web:studio.example.com";
const CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi";
const SOCIAL = "at://did:web:an1m3k4x.etzhayyim.com/app.bsky.feed.post/abc123";

describe("animeka kotoba", () => {
  let e: any;
  beforeEach(() => {
    e = new MockEtzhayyim({ did: "did:web:an1m3k4x.etzhayyim.com" });
  });

  describe("work catalog", () => {
    it("defines + reads + lists by creator; idempotent; validates creatorDid", async () => {
      const r = await defineWork(e, { workId: "W-1", title: "Yukkuri Diaries", creatorDid: CREATOR });
      expect(r.status).toBe("defined");
      expect((await getWork(e, { workId: "W-1" })).work?.title).toBe("Yukkuri Diaries");
      expect((await defineWork(e, { workId: "W-1", title: "dup", creatorDid: CREATOR })).status).toBe("alreadyExists");
      expect((await defineWork(e, { workId: "W-2", title: "x", creatorDid: "nope" })).status).toBe("rejected");
      expect((await listWorks(e, { creatorDid: CREATOR })).total).toBe(1);
    });
  });

  describe("episode lifecycle", () => {
    beforeEach(async () => {
      await defineWork(e, { workId: "W-1", title: "Yukkuri Diaries", creatorDid: CREATOR });
    });
    it("registers draft against existing work; rejects missing work + bad episodeNo", async () => {
      expect((await registerEpisode(e, { episodeId: "E-1", workId: "W-1", episodeNo: 1 })).status).toBe("registered");
      expect((await getEpisode(e, { episodeId: "E-1" })).episode?.status).toBe("draft");
      expect((await registerEpisode(e, { episodeId: "E-X", workId: "GHOST", episodeNo: 1 })).status).toBe("workNotFound");
      expect((await registerEpisode(e, { episodeId: "E-Y", workId: "W-1", episodeNo: 0 })).status).toBe("rejected");
    });
    it("walks draft → published → announced with guards", async () => {
      await registerEpisode(e, { episodeId: "E-1", workId: "W-1", episodeNo: 1 });
      // cannot announce before publish
      expect((await announceEpisode(e, { episodeId: "E-1", socialUri: SOCIAL })).status).toBe("rejected");
      // publish needs a valid CID
      expect((await publishEpisode(e, { episodeId: "E-1", outputCid: "not-a-cid" })).status).toBe("rejected");
      expect((await publishEpisode(e, { episodeId: "E-1", outputCid: CID })).newStatus).toBe("published");
      expect((await getEpisode(e, { episodeId: "E-1" })).episode?.outputCid).toBe(CID);
      // announce needs a valid at:// uri
      expect((await announceEpisode(e, { episodeId: "E-1", socialUri: "https://x" })).status).toBe("rejected");
      expect((await announceEpisode(e, { episodeId: "E-1", socialUri: SOCIAL })).newStatus).toBe("announced");
      // re-publish after announce is rejected
      expect((await publishEpisode(e, { episodeId: "E-1", outputCid: CID })).status).toBe("rejected");
    });
    it("lists by work + status and coverage rolls up", async () => {
      await registerEpisode(e, { episodeId: "E-1", workId: "W-1", episodeNo: 1 });
      await registerEpisode(e, { episodeId: "E-2", workId: "W-1", episodeNo: 2 });
      await publishEpisode(e, { episodeId: "E-2", outputCid: CID });
      expect((await listEpisodes(e, { workId: "W-1" })).total).toBe(2);
      expect((await listEpisodes(e, { workId: "W-1", status: "published" })).total).toBe(1);
      const cov = await coverage(e);
      expect(cov.workCount).toBe(1);
      expect(cov.episodeCount).toBe(2);
      expect(cov.episodesByStatus?.draft).toBe(1);
      expect(cov.episodesByStatus?.published).toBe(1);
    });
  });
});
