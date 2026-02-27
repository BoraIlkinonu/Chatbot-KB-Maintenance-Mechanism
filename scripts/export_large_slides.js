/**
 * Google Apps Script: Export Large Native Google Slides to PPTX
 *
 * Bypasses the 10MB Drive API export limit by using UrlFetchApp,
 * which uses the same backend as the browser "Download as PPTX".
 *
 * REQUIRES: Enable the "Drive API" Advanced Service:
 *   1. In the Apps Script editor, click "Services" (+ icon) in the left sidebar
 *   2. Find "Drive API" and click "Add"
 *
 * SETUP:
 *   1. Go to https://script.google.com and create a new project
 *      Name it "Export Large Files"
 *   2. Paste this entire file into the editor
 *   3. Enable the Drive API Advanced Service (see above)
 *   4. Run setupDailyTrigger() ONCE — this will:
 *      - Ask for permissions (approve them)
 *      - Run the first export immediately
 *      - Set up a daily trigger at 6-7pm UTC (before the midnight UAE pipeline)
 *   5. Done! Exports run automatically every day.
 *
 * The pipeline checks the exports folder for pre-converted PPTX files
 * and downloads those instead of trying the API export.
 */

// ─── CONFIGURATION ──────────────────────────────────────

/**
 * ID of the Drive folder where exported PPTX files will be saved.
 * Open the folder in Drive → copy the ID from the URL after /folders/
 */
var EXPORTS_FOLDER_ID = "1YOBetrxAjn5LBmcU9YzFNNOUQDrCEXcz";

/**
 * Source folders to scan for large native Google Slides.
 * These match the pipeline's TARGET_FOLDERS in config.py.
 */
var SOURCE_FOLDERS = {
  "term1": "17s13FlHGkaNPPlf3jAUY0tSza2yxHqPe",
  "term2": "16UgEwue1ROxFJyPTrowIqTQyduoNEIUb",
  "term3": "1T6zzl0oqltIGcl8M4wAg2xy-z2HDZuxi",
};

// ─── MAIN FUNCTIONS ─────────────────────────────────────

/**
 * Export all native Google Slides from source folders to PPTX.
 * Safe to run multiple times — skips files already exported (unless modified).
 */
function exportAllLargeSlides() {
  // Verify exports folder is accessible
  try {
    Drive.Files.get(EXPORTS_FOLDER_ID);
  } catch (e) {
    Logger.log("ERROR: Cannot access exports folder " + EXPORTS_FOLDER_ID);
    Logger.log("Make sure the folder exists and you have access to it.");
    Logger.log("Error: " + e.message);
    return;
  }

  var existingExports = getExistingExports_();

  var totalExported = 0;
  var totalSkipped = 0;
  var errors = [];

  for (var termKey in SOURCE_FOLDERS) {
    var folderId = SOURCE_FOLDERS[termKey];
    Logger.log("Scanning " + termKey + " (" + folderId + ")...");

    var nativeSlides = findNativeSlides_(folderId);
    Logger.log("  Found " + nativeSlides.length + " native Google Slides files");

    // Create or find term subfolder in exports
    var termFolderId = getOrCreateSubfolder_(EXPORTS_FOLDER_ID, termKey);

    for (var i = 0; i < nativeSlides.length; i++) {
      var file = nativeSlides[i];
      var exportKey = file.id;

      // Skip if already exported and source hasn't changed
      if (existingExports[exportKey]) {
        var existing = existingExports[exportKey];
        if (existing.sourceModified >= file.modifiedTime) {
          Logger.log("  Skipping (unchanged): " + file.name);
          totalSkipped++;
          continue;
        }
        // Source was modified — delete old export and re-export
        Logger.log("  Re-exporting (modified): " + file.name);
        try { Drive.Files.remove(existing.exportFileId); } catch (e) { /* ignore */ }
      }

      try {
        var result = exportSlideToPptx_(file, termFolderId);
        Logger.log("  Exported: " + file.name + " (" + formatBytes_(result.size) + ")");
        totalExported++;
      } catch (e) {
        var errMsg = "  ERROR exporting " + file.name + ": " + e.message;
        Logger.log(errMsg);
        errors.push(errMsg);
      }

      // Rate limiting — avoid quota exhaustion
      Utilities.sleep(2000);
    }
  }

  // Summary
  Logger.log("\n=== Export Summary ===");
  Logger.log("Exported: " + totalExported);
  Logger.log("Skipped (unchanged): " + totalSkipped);
  Logger.log("Errors: " + errors.length);
  if (errors.length > 0) {
    Logger.log("Error details:");
    errors.forEach(function(e) { Logger.log(e); });
  }

  return {
    exported: totalExported,
    skipped: totalSkipped,
    errors: errors.length,
  };
}

/**
 * List all exported files and their source metadata.
 * Useful for debugging.
 */
function listExports() {
  var response = Drive.Files.list({
    q: "'" + EXPORTS_FOLDER_ID + "' in parents and trashed = false",
    fields: "files(id,name,size,description,mimeType)",
    pageSize: 100,
  });

  var files = response.files || [];
  Logger.log("Root files: " + files.length);
  files.forEach(function(f) {
    if (f.mimeType === "application/vnd.google-apps.folder") {
      Logger.log("\n--- Folder: " + f.name + " ---");
      var subResp = Drive.Files.list({
        q: "'" + f.id + "' in parents and trashed = false",
        fields: "files(id,name,size,description)",
        pageSize: 100,
      });
      (subResp.files || []).forEach(function(sf) {
        Logger.log("  " + sf.name + " | " + formatBytes_(parseInt(sf.size || 0)) + " | " + (sf.description || "").substring(0, 50));
      });
    } else {
      Logger.log(f.name + " | " + formatBytes_(parseInt(f.size || 0)) + " | " + (f.description || "").substring(0, 50));
    }
  });
}

/**
 * ONE-TIME SETUP: Run this function to:
 *   1. Export all large slides immediately
 *   2. Install a daily trigger (6-7pm UTC) to keep exports fresh
 *
 * You only need to run this ONCE. It handles everything.
 */
function setupDailyTrigger() {
  // Remove any existing triggers for this function to avoid duplicates
  var triggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === "exportAllLargeSlides") {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }

  // Create daily trigger at 6-7pm UTC (= 10-11pm UAE)
  // This runs before the pipeline's midnight UAE schedule
  ScriptApp.newTrigger("exportAllLargeSlides")
    .timeBased()
    .everyDays(1)
    .atHour(18)  // 6pm UTC = 10pm UAE
    .create();

  Logger.log("Daily trigger installed (6-7pm UTC).");
  Logger.log("Running first export now...\n");

  // Run the first export immediately
  exportAllLargeSlides();
}

/**
 * Clean up all exports (delete everything in the exports folder).
 * Run this if you want to force a full re-export.
 */
function cleanExports() {
  var response = Drive.Files.list({
    q: "'" + EXPORTS_FOLDER_ID + "' in parents and trashed = false",
    fields: "files(id,name,mimeType)",
    pageSize: 200,
  });

  var files = response.files || [];
  files.forEach(function(f) {
    try {
      Drive.Files.remove(f.id);
      Logger.log("Deleted: " + f.name);
    } catch (e) {
      Logger.log("Could not delete " + f.name + ": " + e.message);
    }
  });

  Logger.log("Exports folder cleaned. Deleted " + files.length + " items.");
}

// ─── INTERNAL HELPERS ───────────────────────────────────

/**
 * Export a single Google Slides file to PPTX using UrlFetchApp.
 * This bypasses the 10MB API export limit.
 */
function exportSlideToPptx_(fileInfo, destFolderId) {
  var exportUrl = "https://docs.google.com/presentation/d/" + fileInfo.id + "/export/pptx";

  var response = UrlFetchApp.fetch(exportUrl, {
    headers: {
      "Authorization": "Bearer " + ScriptApp.getOAuthToken(),
    },
    muteHttpExceptions: true,
  });

  if (response.getResponseCode() !== 200) {
    throw new Error("HTTP " + response.getResponseCode() + ": " + response.getContentText().substring(0, 200));
  }

  var blob = response.getBlob();
  // Include parent folder name to avoid collisions (e.g. Students Slides vs Teachers Slides)
  var pathParts = (fileInfo.folderPath || "").split("/");
  var parentFolder = pathParts.length > 0 ? pathParts[pathParts.length - 1] : "";
  var prefix = parentFolder ? parentFolder.replace(/\s+/g, "_") + "__" : "";
  var fileName = prefix + fileInfo.name + ".pptx";
  blob.setName(fileName);

  // Save to Drive with metadata in description for pipeline to read
  var fileMetadata = {
    name: fileName,
    parents: [destFolderId],
    description: JSON.stringify({
      source_id: fileInfo.id,
      source_name: fileInfo.name,
      source_modified: fileInfo.modifiedTime,
      exported_at: new Date().toISOString(),
      folder_path: fileInfo.folderPath || "",
    }),
  };

  var exportedFile = Drive.Files.create(fileMetadata, blob, {
    supportsAllDrives: true,
  });

  return {
    exportFileId: exportedFile.id,
    size: parseInt(exportedFile.size || 0),
  };
}

/**
 * Find all native Google Slides files in a folder using Drive API.
 * Uses Drive Advanced Service (works with shared folders you don't own).
 */
function findNativeSlides_(folderId, folderPath) {
  folderPath = folderPath || "";
  var results = [];
  var pageToken = null;

  do {
    var response = Drive.Files.list({
      q: "'" + folderId + "' in parents and trashed = false",
      fields: "nextPageToken,files(id,name,mimeType,modifiedTime)",
      pageSize: 200,
      pageToken: pageToken,
      supportsAllDrives: true,
      includeItemsFromAllDrives: true,
    });

    var files = response.files || [];
    for (var i = 0; i < files.length; i++) {
      var file = files[i];

      if (file.mimeType === "application/vnd.google-apps.folder") {
        // Recurse into subfolder
        var subPath = folderPath ? folderPath + "/" + file.name : file.name;
        var subResults = findNativeSlides_(file.id, subPath);
        results = results.concat(subResults);
      } else if (file.mimeType === "application/vnd.google-apps.presentation") {
        results.push({
          id: file.id,
          name: file.name,
          modifiedTime: file.modifiedTime,
          folderPath: folderPath,
        });
      }
    }

    pageToken = response.nextPageToken;
  } while (pageToken);

  return results;
}

/**
 * Build a map of existing exports: {sourceFileId: {exportFileId, sourceModified}}
 */
function getExistingExports_() {
  var map = {};

  function scanFolder(parentId) {
    var response = Drive.Files.list({
      q: "'" + parentId + "' in parents and trashed = false",
      fields: "files(id,name,description,mimeType)",
      pageSize: 200,
    });

    var files = response.files || [];
    for (var i = 0; i < files.length; i++) {
      var file = files[i];
      if (file.mimeType === "application/vnd.google-apps.folder") {
        scanFolder(file.id);
      } else {
        try {
          var desc = JSON.parse(file.description || "{}");
          if (desc.source_id) {
            map[desc.source_id] = {
              exportFileId: file.id,
              sourceModified: desc.source_modified || "",
            };
          }
        } catch (e) {
          // Skip files without valid JSON description
        }
      }
    }
  }

  scanFolder(EXPORTS_FOLDER_ID);
  return map;
}

/**
 * Get or create a subfolder by name using Drive API.
 */
function getOrCreateSubfolder_(parentId, name) {
  // Check if subfolder already exists
  var response = Drive.Files.list({
    q: "'" + parentId + "' in parents and name = '" + name + "' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
    fields: "files(id)",
    pageSize: 1,
  });

  if (response.files && response.files.length > 0) {
    return response.files[0].id;
  }

  // Create new subfolder
  var folderMetadata = {
    name: name,
    mimeType: "application/vnd.google-apps.folder",
    parents: [parentId],
  };
  var folder = Drive.Files.create(folderMetadata);
  return folder.id;
}

/**
 * Format bytes to human-readable string.
 */
function formatBytes_(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}
