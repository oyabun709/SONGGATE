/**
 * Centralized file type configuration for SONGGATE.
 * Single source of truth for supported metadata formats on the frontend.
 * Mirror of apps/api/config/file_types.py — keep in sync.
 */

export interface MetadataFormat {
  displayLabel: string;
  internalKey: string;
  mimeTypes: string[];
  fileExtensions: string[];
  inputSupported: boolean;
  outputSupported: boolean;
  displayOrder: number; // 1 = first; DDEX is always 1
  demoSupported: boolean;
  standardSupported: boolean;
}

// DDEX must always be first (displayOrder: 1)
export const DDEX_XML: MetadataFormat = {
  displayLabel: "DDEX XML",
  internalKey: "ddex_xml",
  mimeTypes: ["application/xml", "text/xml"],
  fileExtensions: [".xml"],
  inputSupported: true,
  outputSupported: false,
  displayOrder: 1,
  demoSupported: true,
  standardSupported: true,
};

export const CSV_FORMAT: MetadataFormat = {
  displayLabel: "CSV",
  internalKey: "csv",
  mimeTypes: ["text/csv", "text/plain"],
  fileExtensions: [".csv"],
  inputSupported: true,
  outputSupported: true,
  displayOrder: 2,
  demoSupported: true,
  standardSupported: true,
};

export const JSON_FORMAT: MetadataFormat = {
  displayLabel: "JSON",
  internalKey: "json",
  mimeTypes: ["application/json"],
  fileExtensions: [".json"],
  inputSupported: true,
  outputSupported: true,
  displayOrder: 3,
  demoSupported: true,
  standardSupported: true,
};

// Ordered list — DDEX always first
export const ALL_FORMATS: MetadataFormat[] = [DDEX_XML, CSV_FORMAT, JSON_FORMAT];

// Canonical UI copy — use this string everywhere formats are mentioned
export const FORMAT_DISPLAY_STRING =
  "Work with three supported formats: DDEX XML, CSV, and JSON.";

// accept= string for plain <input type="file"> elements
export const DEMO_ACCEPT_STRING = ".xml,.csv,.json";

// accept map for react-dropzone
export const DEMO_ACCEPT_DROPZONE: Record<string, string[]> = {
  "application/xml": [".xml"],
  "text/xml": [".xml"],
  "text/csv": [".csv"],
  "text/plain": [".csv"],
  "application/json": [".json"],
};
