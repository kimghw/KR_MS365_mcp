/* Tool Editor State - Global Variables */

let tools = [];
let internalArgs = {};  // Internal args (hidden from MCP signature)
let signatureDefaults = {};  // Signature params with internal defaults (shown to LLM but has fallback values)
let fileMtimes = {};    // File modification times for conflict detection
let currentToolIndex = -1;
let nestedGraphTarget = null;
let currentProfile = '';
let profiles = [];
let generatorModules = [];
let generatorFallback = {};
let templateSources = [];  // Available template files (current, backups, other profiles)
let originalProfile = '';  // The profile that tools were originally loaded from (for saving)
let serverControlProfile = '';  // The profile used for server control (independent of tool editing profile)
let debugIndexEnabled = false;
let debugIndexObserver = null;
let debugIndexRefreshPending = false;
let debugMetadataDirty = true;
