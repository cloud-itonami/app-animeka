(ns lg-animeka.util
  "Shared pure helpers for the lg-animeka clj port (ADR-2606280030).

  These mirror the small private helpers duplicated across the Python graph
  modules (`_rkey_from_id`, `_gen_rkey`, `_cid_stub`, clip, clamp, camel/snake
  conversion). They are host-independent pure functions, so they verify under
  bb with no external runtime."
  (:require [clojure.string :as str]))

(def ^:dynamic app-did "did:web:animeka.etzhayyim.com")

(def ^:dynamic repo-did "did:web:an1m3k4x.etzhayyim.com")

(defn rkey-from-id
  "at://repo/coll/rkey  →  rkey ; a bare rkey is returned unchanged.
  Mirrors the `_rkey_from_id` helper duplicated across the Python graphs."
  [val]
  (let [v (str val)]
    (if (str/starts-with? v "at://")
      (-> v (str/replace #"/+$" "") (str/split #"/") last)
      v)))

(defn clip
  "First n chars of (str s) — yt-dlp/error/url truncation parity."
  [s n]
  (let [s (str s)] (subs s 0 (min n (count s)))))

(defn clamp
  "Clamp x into [lo hi] after coercing to a long; nil/blank → default d first."
  [x d lo hi]
  (let [n (cond
            (number? x) (long x)
            (and (string? x) (re-matches #"-?\d+" (str/trim x)))
            #?(:clj (Long/parseLong (str/trim x))
               :cljs (js/parseInt (str/trim x) 10))
            :else (long d))]
    (max lo (min hi n))))

(defn gen-rkey
  "`{prefix}-{8 hex}` record key (secrets.token_hex(4) parity)."
  ([] (gen-rkey "rec"))
  ([prefix]
   (let [hex (apply str (repeatedly 8 #(rand-nth "0123456789abcdef")))]
     (str prefix "-" hex))))

(defn cid-stub
  "sha256(vertex-id)[:32] — the Python `_cid_stub` placeholder CID."
  [vertex-id]
  #?(:clj
     (let [md (java.security.MessageDigest/getInstance "SHA-256")
           bs (.digest md (.getBytes (str vertex-id) "UTF-8"))]
       (subs (apply str (map #(format "%02x" %) bs)) 0 32))
     :default (subs (str (hash vertex-id)) 0 (min 32 (count (str (hash vertex-id)))))))

(defn now-iso
  "UTC ISO-8601 timestamp (datetime.now(tz=utc).isoformat() parity)."
  []
  #?(:clj (.toString (java.time.Instant/now))
     :default ""))

(defn camel->snake
  "fooBarBaz → foo_bar_baz (server._camel_to_snake parity)."
  [s]
  (let [s (str s)]
    (->> (map-indexed
          (fn [i ch]
            (let [c (str ch)]
              (if (and (pos? i) (= c (str/upper-case c)) (not= c (str/lower-case c)))
                (str "_" (str/lower-case c))
                (str/lower-case c))))
          s)
         (apply str))))

(defn at-uri [did coll rkey] (str "at://" did "/" coll "/" rkey))
