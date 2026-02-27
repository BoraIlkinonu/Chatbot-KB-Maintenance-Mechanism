/**
 * Google Apps Script: Export Large Native Google Slides to PPTX
 *
 * Bypasses the 10MB Drive API export limit by using UrlFetchApp,
 * which uses the same backend as the browser "Download as PPTX".
 *
 * SETUP:
 *   1. Go to https://script.google.com and create a new project
 *   2. Paste this entire file into the editor
 *   3. Set EXPORTS_FOLDER_ID below to a Drive folder you own
 *   4. Run exportAllLargeSlides() — it will ask for permissions on first run
 *   5. (Optional) Set a time-based trigger to run daily before the pipeline
 *
 * The pipeline will check the exports folder for pre-converted PPTX files
 * and download those instead of trying the API export.
 */

// ─── CONFIGURATION ──────────────────────────────────────

/**
 * ID of the Drive folder where exported PPTX files will be saved.
 * Create a folder in your Drive and paste its ID here.
 * (The folder ID is the last part of the folder URL)
 */
var EXPORTS_FOLDER_ID = "YOUR_EXPORTS_FOLDER_ID_HERE";

/**
 * Source folders to scan for large native Google Slides.
 * These match the pipeline's TARGET_FOLDERS in config.py.
 */
var SOURCE_FOLDERS = {
  "term1": "17s13FlHGkaNPPlf3jAUY0tSza2yxHqPe",
  "term2": "1T6zzl0oqltIGcl8M4wAg2xy-z2HDZuxi",
  "term3": "16UgEwue1ROxFJyPTrowIqTQyduoNEIUb",
};

/**
 * Minimum file size (in slides) to trigger export.
 * Files with fewer slides are small enough for the API export.
 * Set to 0 to export ALL native Slides files.
 */
var MIN_SLIDES_FOR_EXPORT = 0;

// ─── MAIN FUNCTIONS ─────────────────────────────────────

/**
 * Export all large native Google Slides from source folders to PPTX.
 * Safe to run multiple times — skips files already exported (unless modified).
 */
function exportAllLargeSlides() {
  var exportsFolder = DriveApp.getFolderById(EXPORTS_FOLDER_ID);
  var existingExports = getExistingExports_(exportsFolder);

  var totalExported = 0;
  var totalSkipped = 0;
  var errors = [];

  for (var termKey in SOURCE_FOLDERS) {
    var folderId = SOURCE_FOLDERS[termKey];
    Logger.log("Scanning " + termKey + " (" + folderId + ")...");

    var nativeSlides = findNativeSlides_(folderId);
    Logger.log("  Found " + nativeSlides.length + " native Google Slides files");

    // Create term subfolder in exports
    var termFolder = getOrCreateSubfolder_(exportsFolder, termKey);

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
        DriveApp.getFileById(existing.exportFileId).setTrashed(true);
      }

      try {
        var result = exportSlideToPptx_(file, termFolder);
        Logger.log("  Exported: " + file.name + " (" + formatBytes_(result.size) + ")");
        totalExported++;
      } catch (e) {
        var errMsg = "  ERROR exporting " + file.name + ": " + e.message;
        Logger.log(errMsg);
        errors.push(errMsg);
      }

      // Rate limiting — avoid quota exhaustion
      Utilities.sleep(1000);
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
  var exportsFolder = DriveApp.getFolderById(EXPORTS_FOLDER_ID);
  var files = exportsFolder.getFiles();

  while (files.hasNext()) {
    var file = files.next();
    var desc = file.getDescription() || "";
    Logger.log(file.getName() + " | " + formatBytes_(file.getSize()) + " | " + desc);
  }

  // Also check subfolders
  var folders = exportsFolder.getFolders();
  while (folders.hasNext()) {
    var folder = folders.next();
    Logger.log("\n--- " + folder.getName() + " ---");
    var subFiles = folder.getFiles();
    while (subFiles.hasNext()) {
      var f = subFiles.next();
      Logger.log(f.getName() + " | " + formatBytes_(f.getSize()) + " | " + (f.getDescription() || ""));
    }
  }
}

/**
 * Clean up all exports (delete everything in the exports folder).
 * Run this if you want to force a full re-export.
 */
function cleanExports() {
  var exportsFolder = DriveApp.getFolderById(EXPORTS_FOLDER_ID);

  // Delete files in root
  var files = exportsFolder.getFiles();
  while (files.hasNext()) {
    files.next().setTrashed(true);
  }

  // Delete subfolders
  var folders = exportsFolder.getFolders();
  while (folders.hasNext()) {
    folders.next().setTrashed(true);
  }

  Logger.log("Exports folder cleaned.");
}

// ─── INTERNAL HELPERS ───────────────────────────────────

/**
 * Export a single Google Slides file to PPTX using UrlFetchApp.
 * This bypasses the 10MB API export limit.
 */
function exportSlideToPptx_(fileInfo, destFolder) {
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
  var fileName = fileInfo.name + ".pptx";
  blob.setName(fileName);

  // Save to Drive with metadata in description for pipeline to read
  var exportedFile = destFolder.createFile(blob);
  exportedFile.setDescription(JSON.stringify({
    source_id: fileInfo.id,
    source_name: fileInfo.name,
    source_modified: fileInfo.modifiedTime,
    exported_at: new Date().toISOString(),
    folder_path: fileInfo.folderPath || "",
  }));

  return {
    exportFileId: exportedFile.getId(),
    size: exportedFile.getSize(),
  };
}

/**
 * Recursively find all native Google Slides files in a folder.
 */
function findNativeSlides_(folderId, folderPath) {
  folderPath = folderPath || "";
  var results = [];
  var folder = DriveApp.getFolderById(folderId);

  // Find Google Slides files
  var files = folder.getFilesByType(MimeType.GOOGLE_SLIDES);
  while (files.hasNext()) {
    var file = files.next();
    results.push({
      id: file.getId(),
      name: file.getName(),
      modifiedTime: file.getLastUpdated().toISOString(),
      folderPath: folderPath,
    });
  }

  // Recurse into subfolders
  var subfolders = folder.getFolders();
  while (subfolders.hasNext()) {
    var sub = subfolders.next();
    var subPath = folderPath ? folderPath + "/" + sub.getName() : sub.getName();
    var subResults = findNativeSlides_(sub.getId(), subPath);
    results = results.concat(subResults);
  }

  return results;
}

/**
 * Build a map of existing exports: {sourceFileId: {exportFileId, sourceModified}}
 */
function getExistingExports_(exportsFolder) {
  var map = {};

  function scanFolder(folder) {
    var files = folder.getFiles();
    while (files.hasNext()) {
      var file = files.next();
      try {
        var desc = JSON.parse(file.getDescription() || "{}");
        if (desc.source_id) {
          map[desc.source_id] = {
            exportFileId: file.getId(),
            sourceModified: desc.source_modified || "",
          };
        }
      } catch (e) {
        // Skip files without valid JSON description
      }
    }

    var subfolders = folder.getFolders();
    while (subfolders.hasNext()) {
      scanFolder(subfolders.next());
    }
  }

  scanFolder(exportsFolder);
  return map;
}

/**
 * Get or create a subfolder by name.
 */
function getOrCreateSubfolder_(parentFolder, name) {
  var folders = parentFolder.getFoldersByName(name);
  if (folders.hasNext()) {
    return folders.next();
  }
  return parentFolder.createFolder(name);
}

/**
 * Format bytes to human-readable string.
 */
function formatBytes_(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}
