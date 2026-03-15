export const SYSTEM_TOKENS: string[] = [
  'InputFile', 'InputFile:',
  'Job', 'JobName',
  'LastOutput', 'LastOutput:',
  'Output:', 'AllOutputBefore',
  'Suffix', 'Suffix:',
  'ThreadN', 'Workspace', 'UserBin',
  'History'
]

export function buildTokens(referenceNames: string[]): string[] {
  const refs = (referenceNames || []).filter(Boolean)
  return Array.from(new Set([ ...SYSTEM_TOKENS, ...refs ])).sort((a, b) => a.localeCompare(b))
}



