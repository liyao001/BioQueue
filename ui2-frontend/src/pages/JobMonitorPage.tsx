import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { formatBytes } from '../lib/format'
import { apiGet, apiPost, apiDelete, apiPatch } from '../lib/api'
import { useToast, Modal, ModalOverlay, ModalContent, ModalHeader, ModalCloseButton, ModalBody, Flex, Box, Input, Button, ButtonGroup, Heading, Select, Menu, MenuButton, MenuList, MenuOptionGroup, MenuItemOption, MenuItem, Portal, Spinner, HStack, Text, IconButton, Table, Thead, Tbody, Tr, Th, Td, Checkbox, SimpleGrid, Tooltip, Image, Link as ChakraLink, Slider, SliderTrack, SliderFilledTrack, SliderThumb, Textarea } from '@chakra-ui/react'
import Pager from '../components/Pager'
import JobResultsPicker from '../components/JobResultsPicker'
import { Link as RouterLink, useLocation, useNavigate } from 'react-router-dom'


type Job = {
  id: number
  job_name: string
  status: number
  protocol: number
  protocol_ver?: string
  protocol_name?: string
  workspace_id?: number
  workspace_name?: string
  locked?: number
  version?: number
  result?: string
  create_time?: string
  update_time?: string
  comments?: string
  parameter?: string
  input_file?: string
  slave?: number | null
  slave_name?: string
  visibility?: number
}


type JobFile = { name: string; file_size: number; file_create: string; trace: string; is_link: boolean }

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'} as any)[c] || c)
}

// extractError
async function extractError(res: Response): Promise<string> {
  try {
    const data = await res.json()
    return (data?.detail || data?.info || JSON.stringify(data))
  } catch {
    try {
      const txt = await res.text()
      return txt || `${res.status}`
    } catch {
      return `${res.status}`
    }
  }
}

// presentational components
const FilesTable = React.memo(function FilesTable({
  files,
  sortField,
  sortOrder,
  onSort,
  onPreview,
  onDownload,
  onDelete,
}: {
  files: JobFile[]
  sortField: 'name'|'size'|'created'
  sortOrder: 'asc'|'desc'
  onSort: (field: 'name'|'size'|'created') => void
  onPreview: (file: JobFile) => void
  onDownload: (file: JobFile) => void
  onDelete: (file: JobFile) => void
}) {
  return (
    <Table size="sm" variant="simple" width="100%">
      <Thead>
        <Tr>
          <Th textAlign="left" py={1}>
            <Button variant="link" size="sm" onClick={()=>onSort('name')}>
              Name {sortField==='name' ? (sortOrder==='asc'?'▲':'▼') : ''}
            </Button>
          </Th>
          <Th textAlign="left" py={1}>
            <Button variant="link" size="sm" onClick={()=>onSort('size')}>
              Size {sortField==='size' ? (sortOrder==='asc'?'▲':'▼') : ''}
            </Button>
          </Th>
          <Th textAlign="left" py={1}>
            <Button variant="link" size="sm" onClick={()=>onSort('created')}>
              Created {sortField==='created' ? (sortOrder==='asc'?'▲':'▼') : ''}
            </Button>
          </Th>
          <Th textAlign="left" py={1}>Actions</Th>
        </Tr>
      </Thead>
      <Tbody>
        {files.map(f => (
          <Tr key={f.trace} data-trace={f.trace}>
            <Td py={1} pr={2} wordBreak="break-all">
              {f.is_link && <i className="fa-solid fa-link" style={{ marginRight: '0.25rem', opacity: 0.7 }} title="link"></i>}
              <Button variant="link" size="sm" colorScheme="blue" onClick={()=>onPreview(f)} title="preview">
                {f.name}
              </Button>
            </Td>
            <Td py={1} pr={2}>{formatBytes(Number(f.file_size))}</Td>
            <Td py={1} pr={2}>{f.file_create}</Td>
            <Td py={1} pr={2}>
              <ButtonGroup isAttached>
                <Tooltip label="Download">
                  <IconButton aria-label="download" size="sm" colorScheme="blue" onClick={()=>onDownload(f)} icon={<i className="fa-solid fa-download"></i>} />
                </Tooltip>
                <Tooltip label="Preview">
                  <IconButton aria-label="preview" size="sm" colorScheme="teal" onClick={()=>onPreview(f)} icon={<i className="fa-regular fa-eye"></i>} />
                </Tooltip>
                <Tooltip label="Delete">
                  <IconButton aria-label="delete" size="sm" colorScheme="red" onClick={()=>onDelete(f)} icon={<i className="fa-solid fa-trash"></i>} />
                </Tooltip>
              </ButtonGroup>
            </Td>
          </Tr>
        ))}
      </Tbody>
    </Table>
  )
})

const PreviewToolbar = React.memo(function PreviewToolbar({
  onBack,
  onOpenNewWindow,
  onDownload,
}: {
  onBack: () => void
  onOpenNewWindow: () => void
  onDownload: () => void
}) {
  return (
    <ButtonGroup variant="outline" isAttached>
      <Tooltip label="Back to files"><Button size="sm" variant="outline" onClick={onBack}><i className="fa-solid fa-arrow-left"></i></Button></Tooltip>
      <Tooltip label="Open in new window"><Button size="sm" variant="outline" mr={2} onClick={onOpenNewWindow}><i className="fa-solid fa-arrow-up-right-from-square"></i></Button></Tooltip>
      <Tooltip label="Download"><Button size="sm" onClick={onDownload}><i className="fa-solid fa-download"></i></Button></Tooltip>
    </ButtonGroup>
  )
})

// page sections
function FiltersHeader(props: {
  nameOrIdInput: string
  setNameOrIdInput: (v: string) => void
  jobNameNot: string
  setJobNameNot: (v: string) => void
  parameter: string
  setParameter: (v: string) => void
  parameterNot: string
  setParameterNot: (v: string) => void
  inputFile: string
  setInputFile: (v: string) => void
  inputFileNot: string
  setInputFileNot: (v: string) => void
  protocolId: string
  setProtocolId: (v: string) => void
  protocolName: string
  setProtocolName: (v: string) => void
  protocolNameNot: string
  setProtocolNameNot: (v: string) => void
  workspaceId: string
  setWorkspaceId: (v: string) => void
  workspaceName: string
  setWorkspaceName: (v: string) => void
  workspaceNameNot: string
  setWorkspaceNameNot: (v: string) => void
  statusChoices: { value: number; label: string }[]
  statusSel: number[]
  setStatusSel: (v: number[]) => void
  setStatusText: (v: string) => void
  statusNotSel: number[]
  setStatusNotSel: (v: number[]) => void
  setStatusNotText: (v: string) => void
  idNotText: string
  setIdNotText: (v: string) => void
  mode: 'all'|'any'
  setMode: (v: 'all'|'any') => void
  loading: boolean
  runSearch: (e?: React.FormEvent) => void
  pageSize: number
  setPageSize: (n: number) => void
  setPage: (n: number) => void
  viewMode: 'table'|'cards'
  setViewMode: (m: 'table'|'cards') => void
  autoRefresh: boolean
  setAutoRefresh: (b: boolean) => void
  selectedIdsCount: number
  bulkAction: (ids: number[], action: 'terminate'|'rerun_clean'|'rerun_insitu'|'delete') => void
  selectedIds: number[]
  // dropdown data
  protocols: {id:number; name:string}[]
  workspaces: {id:number; name:string}[]
  protocolFilter: string
  setProtocolFilter: (v: string) => void
  workspaceFilter: string
  setWorkspaceFilter: (v: string) => void
  loadingProtocols: boolean
  loadingWorkspaces: boolean
  showProtoDD: boolean
  setShowProtoDD: (b: boolean) => void
  showWsDD: boolean
  setShowWsDD: (b: boolean) => void
  showStatusDD: boolean
  setShowStatusDD: (b: boolean) => void
  showStatusNotDD: boolean
  setShowStatusNotDD: (b: boolean) => void
  showAdvancedFilters: boolean
  setShowAdvancedFilters: (b: boolean) => void
}) {
  const {
    nameOrIdInput, setNameOrIdInput,
    jobNameNot, setJobNameNot,
    parameter, setParameter,
    parameterNot, setParameterNot,
    inputFile, setInputFile,
    inputFileNot, setInputFileNot,
    protocolId, setProtocolId,
    protocolName, setProtocolName,
    protocolNameNot, setProtocolNameNot,
    workspaceId, setWorkspaceId,
    workspaceName, setWorkspaceName,
    workspaceNameNot, setWorkspaceNameNot,
    statusChoices, statusSel, setStatusSel, setStatusText,
    statusNotSel, setStatusNotSel, setStatusNotText,
    idNotText, setIdNotText,
    mode, setMode,
    loading, runSearch, pageSize, setPageSize, setPage,
    viewMode, setViewMode,
    autoRefresh, setAutoRefresh,
    selectedIdsCount, bulkAction, selectedIds,
    protocols, workspaces,
    protocolFilter, setProtocolFilter,
    workspaceFilter, setWorkspaceFilter,
    loadingProtocols, loadingWorkspaces,
    showProtoDD, setShowProtoDD,
    showWsDD, setShowWsDD,
    showStatusDD, setShowStatusDD,
    showStatusNotDD, setShowStatusNotDD,
    showAdvancedFilters, setShowAdvancedFilters,
  } = props
  const selectedStatusLabels = useMemo(() => statusChoices.filter(s => statusSel.includes(s.value)).map(s => s.label), [statusChoices, statusSel])
  const selectedStatusNotLabels = useMemo(() => statusChoices.filter(s => statusNotSel.includes(s.value)).map(s => s.label), [statusChoices, statusNotSel])
  return (
    <Box as="form" onSubmit={runSearch} mb={4}>
      {/* Basic Filters - Always Visible */}
      <Flex align="center" gap={1} wrap="wrap" mb={2} w="100%">
        <Box flex="2" minW="180px">
          <Input aria-label="Job name or IDs" value={nameOrIdInput} onChange={(e)=>{ setNameOrIdInput(e.target.value) }} placeholder="job name or IDs (comma/space)" />
        </Box>

        <Box position="relative" flex="2" minW="140px">
          <Menu isOpen={showProtoDD} onClose={()=>setShowProtoDD(false)}>
            <MenuButton as={Button} onClick={()=>{ setShowProtoDD(!showProtoDD); setShowWsDD(false); setShowStatusDD(false); setShowStatusNotDD(false); }} w="100%" textAlign="left">
              Protocol: {protocolId ? (protocols.find(p=>String(p.id)===protocolId)?.name || protocolId) : 'all'}
            </MenuButton>
            <Portal>
              <MenuList minW="320px" p={2} maxH="300px" overflowY="auto" sx={{ WebkitOverflowScrolling: 'touch' }}>
                <Input size="sm" placeholder="filter protocols" mb={2} value={protocolFilter} onChange={(e)=>setProtocolFilter(e.target.value)} />
                <MenuOptionGroup type="radio" value={protocolId} onChange={(val)=>{ const v = String((val as any) ?? ''); setProtocolId(v); setShowProtoDD(false); setPage(1); setTimeout(()=>runSearch(), 0); }}>
                  <MenuItemOption value="">all</MenuItemOption>
                  {protocols.map(p => (
                    <MenuItemOption key={p.id} value={String(p.id)}>{p.id} - {p.name}</MenuItemOption>
                  ))}
                </MenuOptionGroup>
                {loadingProtocols && <Box fontSize="sm" opacity={0.6} mt={2}>loading…</Box>}
              </MenuList>
            </Portal>
          </Menu>
        </Box>

        <Box position="relative" flex="2" minW="140px">
          <Menu isOpen={showWsDD} onClose={()=>setShowWsDD(false)}>
            <MenuButton as={Button} onClick={()=>{ setShowWsDD(!showWsDD); setShowProtoDD(false); setShowStatusDD(false); setShowStatusNotDD(false); }} w="100%" textAlign="left">
              Workspace: {workspaceId ? (workspaces.find(w=>String(w.id)===workspaceId)?.name || workspaceId) : 'all'}
            </MenuButton>
            <Portal>
              <MenuList minW="300px" p={2} maxH="300px" overflowY="auto" sx={{ WebkitOverflowScrolling: 'touch' }}>
                <Input size="sm" placeholder="filter workspaces" mb={2} value={workspaceFilter} onChange={(e)=>setWorkspaceFilter(e.target.value)} />
                <MenuOptionGroup type="radio" value={workspaceId} onChange={(val)=>{ const v = String((val as any) ?? ''); setWorkspaceId(v); setShowWsDD(false); setPage(1); setTimeout(()=>runSearch(), 0); }}>
                  <MenuItemOption value="">all</MenuItemOption>
                  {workspaces.map(w => (
                    <MenuItemOption key={w.id} value={String(w.id)}>{w.name}</MenuItemOption>
                  ))}
                </MenuOptionGroup>
                {loadingWorkspaces && <Box fontSize="sm" opacity={0.6} mt={2}>loading…</Box>}
              </MenuList>
            </Portal>
          </Menu>
        </Box>

        <Box position="relative" flex="1" minW="120px">
          <Menu isOpen={showStatusDD} onClose={()=>{ setShowStatusDD(false); setPage(1); setTimeout(()=>runSearch(), 0) }}>
            <MenuButton as={Button} onClick={()=>{ setShowStatusDD(!showStatusDD); setShowProtoDD(false); setShowWsDD(false); setShowStatusNotDD(false); }} w="100%" textAlign="left">
              Status: {selectedStatusLabels.length === 0 ? 'any' : selectedStatusLabels.length === 1 ? selectedStatusLabels[0] : `${selectedStatusLabels.length} selected`}
            </MenuButton>
            <Portal>
              <MenuList minW="260px" p={2}>
                <MenuOptionGroup type="checkbox" value={statusSel.map(String)} onChange={(vals)=>{
                  const arr = (Array.isArray(vals) ? vals : [vals]).filter(Boolean).map(v=>parseInt(String(v)))
                  setStatusSel(arr)
                  setStatusText(arr.join(','))
                }}>
                  {statusChoices.map(s => (
                    <MenuItemOption key={s.value} value={String(s.value)}>{s.label}</MenuItemOption>
                  ))}
                </MenuOptionGroup>
                <Flex justify="flex-end" gap={2} mt={2}>
                  <Button size="sm" variant="outline" onClick={()=>{ setStatusSel([]); setStatusText(''); setShowStatusDD(false); setPage(1); setTimeout(()=>runSearch(), 0) }}>Clear</Button>
                  <Button size="sm" variant="outline" onClick={()=>{ setShowStatusDD(false); setPage(1); setTimeout(()=>runSearch(), 0) }}>Done</Button>
                </Flex>
              </MenuList>
            </Portal>
          </Menu>
        </Box>


        <Button
          size="sm"
          variant="ghost"
          onClick={() => setShowAdvancedFilters(!showAdvancedFilters)}
          leftIcon={<i className={`fa-solid fa-chevron-${showAdvancedFilters ? 'up' : 'down'}`}></i>}
          flex="1"
          minW="130px"
          justifyContent="flex-start"
        >
          {showAdvancedFilters ? 'Hide' : 'Show'} Advanced
        </Button>

        <Button
          type="button"
          colorScheme="blue"
          title="Refresh search results"
          isDisabled={loading}
          flexShrink={0}
          ml={2}
          onClick={() => runSearch()}
        >
          {loading ? (
            <Spinner size="sm" />
          ) : (
            <i className="fa-solid fa-refresh"></i>
          )}
        </Button>
      </Flex>

      {/* Advanced Filters - Conditionally Visible */}
      {showAdvancedFilters && (
        <>
          {/* Row 1: Name exclusions */}
          <Flex align="center" gap={1} wrap="wrap" mb={2} w="100%">
            <Box flex="1" minW="140px">
              <Input aria-label="Job name exclude" value={jobNameNot} onChange={(e)=>{ setJobNameNot(e.target.value); }} placeholder="exclude job names" />
            </Box>
            <Box flex="1" minW="120px">
              <Input aria-label="Protocol name" value={protocolName} onChange={(e)=>{ setProtocolName(e.target.value); }} placeholder="protocol name search" />
            </Box>
            <Box flex="1" minW="120px">
              <Input aria-label="Protocol name exclude" value={protocolNameNot} onChange={(e)=>{ setProtocolNameNot(e.target.value); }} placeholder="exclude protocols" />
            </Box>
            <Box flex="1" minW="120px">
              <Input aria-label="Workspace name" value={workspaceName} onChange={(e)=>{ setWorkspaceName(e.target.value); }} placeholder="workspace name search" />
            </Box>
            <Box flex="1" minW="120px">
              <Input aria-label="Workspace name exclude" value={workspaceNameNot} onChange={(e)=>{ setWorkspaceNameNot(e.target.value); }} placeholder="exclude workspaces" />
            </Box>
          </Flex>

          {/* Row 2: Content search filters */}
          <Flex align="center" gap={1} wrap="wrap" mb={2} w="100%">
            <Box flex="1" minW="130px">
              <Input aria-label="Parameters" value={parameter} onChange={(e)=>{ setParameter(e.target.value); }} placeholder="search parameters" />
            </Box>
            <Box flex="1" minW="130px">
              <Input aria-label="Parameters exclude" value={parameterNot} onChange={(e)=>{ setParameterNot(e.target.value); }} placeholder="exclude parameters" />
            </Box>
            <Box flex="1" minW="130px">
              <Input aria-label="Input files" value={inputFile} onChange={(e)=>{ setInputFile(e.target.value); }} placeholder="search input files" />
            </Box>
            <Box flex="1" minW="130px">
              <Input aria-label="Input files exclude" value={inputFileNot} onChange={(e)=>{ setInputFileNot(e.target.value); }} placeholder="exclude input files" />
            </Box>
          </Flex>

          {/* Row 3: Status exclude and exclude Job IDs */}
          <Flex align="center" gap={1} wrap="wrap" mb={2} w="100%">
            <Box position="relative" flex="1" minW="120px">
              <Menu isOpen={showStatusNotDD} onClose={()=>{ setShowStatusNotDD(false); setPage(1); setTimeout(()=>runSearch(), 0) }}>
                <MenuButton as={Button} onClick={()=>{ setShowStatusNotDD(!showStatusNotDD); setShowProtoDD(false); setShowWsDD(false); setShowStatusDD(false); }} w="100%" textAlign="left">
                  Status ≠: {selectedStatusNotLabels.length === 0 ? 'any' : selectedStatusNotLabels.length === 1 ? selectedStatusNotLabels[0] : `${selectedStatusNotLabels.length} selected`}
                </MenuButton>
                <Portal>
                  <MenuList minW="260px" p={2}>
                    <MenuOptionGroup type="checkbox" value={statusNotSel.map(String)} onChange={(vals)=>{
                      const arr = (Array.isArray(vals) ? vals : [vals]).filter(Boolean).map(v=>parseInt(String(v)))
                      setStatusNotSel(arr)
                      setStatusNotText(arr.join(','))
                    }}>
                      {statusChoices.map(s => (
                        <MenuItemOption key={s.value} value={String(s.value)}>{s.label}</MenuItemOption>
                      ))}
                    </MenuOptionGroup>
                    <Flex justify="flex-end" gap={2} mt={2}>
                      <Button size="sm" variant="outline" onClick={()=>{ setStatusNotSel([]); setStatusNotText(''); setShowStatusNotDD(false); setPage(1); setTimeout(()=>runSearch(), 0) }}>Clear</Button>
                      <Button size="sm" variant="outline" onClick={()=>{ setShowStatusNotDD(false); setPage(1); setTimeout(()=>runSearch(), 0) }}>Done</Button>
                    </Flex>
                  </MenuList>
                </Portal>
              </Menu>
            </Box>

            <Box flex="1" minW="120px">
              <Input aria-label="Exclude Job IDs" value={idNotText} onChange={(e)=>{ setIdNotText(e.target.value); }} placeholder="exclude Job IDs" />
            </Box>
            <Flex align="center" gap={2} flex="1" minW="120px">
              <Box as="label" fontSize="sm" whiteSpace="nowrap">Mode:</Box>
              <ButtonGroup variant="outline" isAttached>
                <Button size="sm" variant={mode === 'all' ? 'solid' : 'outline'} onClick={()=>setMode('all')} colorScheme={mode === 'all' ? 'blue' : undefined}>AND</Button>
                <Button size="sm" variant={mode === 'any' ? 'solid' : 'outline'} onClick={()=>setMode('any')} colorScheme={mode === 'any' ? 'blue' : undefined}>OR</Button>
              </ButtonGroup>
            </Flex>
          </Flex>
        </>
      )}

      <Flex mt={2} align="center" gap={3} wrap="wrap">
        <Flex align="center" gap={2}>
          <Box as="label" fontSize="sm">page size</Box>
          <Select value={pageSize} onChange={(e)=>{ const v = parseInt(e.target.value)||12; setPageSize(v); }} width="auto">
            {[12,24,36,48].map(s => <option key={s} value={s}>{s}</option>)}
          </Select>
        </Flex>
        <Flex align="center" gap={2} fontSize="sm">
          <Box as="span">view</Box>
          <ButtonGroup variant="outline" isAttached>
              <Button size="sm" variant={viewMode==='cards'?'solid':'outline'} onClick={()=>setViewMode('cards')} title="cards"><i className="fa-solid fa-clipboard-list"></i></Button>
              <Button size="sm" variant={viewMode==='table'?'solid':'outline'} onClick={()=>setViewMode('table')} title="table"><i className="fa-solid fa-table-list"></i></Button>
          </ButtonGroup>
        </Flex>
        <Flex align="center" gap={2}>
          <Button size="sm" variant={autoRefresh ? 'solid' : 'outline'} onClick={()=>setAutoRefresh(!autoRefresh)}>
            auto refresh
          </Button>
          <Button size="sm" variant="outline" onClick={()=>runSearch()}>refresh now</Button>
        </Flex>
        {selectedIdsCount > 0 && (
          <Flex align="center" gap={2} ml="auto">
            <Box fontSize="sm">selected {selectedIdsCount}</Box>
            <Button size="sm" variant="outline" onClick={()=>bulkAction(selectedIds, 'terminate')}>terminate</Button>
            <Button size="sm" variant="outline" onClick={()=>bulkAction(selectedIds, 'rerun_clean')}>rerun</Button>
            <Button size="sm" variant="outline" onClick={()=>bulkAction(selectedIds, 'rerun_insitu')}>rerun in-situ</Button>
            <Button size="sm" colorScheme="red" variant="outline" onClick={()=>bulkAction(selectedIds, 'delete')}>delete</Button>
          </Flex>
        )}
      </Flex>
    </Box>
  )
}

function JobTable(props: {
  results: Job[]
  selectedIds: number[]
  isSelected: (id: number)=>boolean
  toggleSelect: (id: number)=>void
  toggleSelectAllCurrent: ()=>void
  statusMap: Map<number, string>
  doChangeVisibility: (id: number, vis: number)=>void
  doTerminate: (id: number)=>void
  doRerun: (id: number, insitu: boolean)=>void
  doLockToggle: (id: number)=>void
  showFiles: (job: Job)=>void
  showLog: (job: Job, type: 'out'|'err')=>void
  showHistory: (job: Job)=>void
  doDeleteJob: (id: number)=>void
  notify: (msg: string, type?: 'success'|'error')=>void
  fetchAndReplaceJob: (id: number)=>Promise<void>
  setOpenModal: (v: any)=>void
  setEditValue: (v: string)=>void
}) {
  const {
    results, selectedIds, isSelected, toggleSelect, toggleSelectAllCurrent,
    statusMap, doChangeVisibility, doTerminate, doRerun, doLockToggle,
    showFiles, showLog, showHistory, doDeleteJob,
    notify, fetchAndReplaceJob, setOpenModal, setEditValue,
  } = props
  // These props are used in inline event handlers but not directly in JSX
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  void doLockToggle
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  void showFiles
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  void showLog
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  void setEditValue
  return (
    <Box overflowX="auto">
      <Table size="sm" variant="simple">
        <Thead>
          <Tr>
            <Th><Checkbox isChecked={results.length>0 && results.every(r=>selectedIds.includes(r.id))} onChange={toggleSelectAllCurrent} /></Th>
            <Th>id</Th>
            <Th>name</Th>
            <Th>status</Th>
            <Th>protocol</Th>
            <Th>workspace</Th>
            <Th>ver</Th>
            <Th>result</Th>
            <Th>created</Th>
            <Th>updated</Th>
            <Th>actions</Th>
          </Tr>
        </Thead>
        <Tbody>
          {results.map((j) => (
            <Tr key={j.id} _hover={{ bg: 'gray.50' }}>
              <Td><Checkbox isChecked={isSelected(j.id)} onChange={()=>toggleSelect(j.id)} /></Td>
              <Td>{j.id}</Td>
              <Td>{j.job_name}</Td>
              <Td><StatusBadge n={j.status} label={statusMap.get(j.status) || String(j.status)} /></Td>
              <Td>{j.protocol_name || j.protocol}</Td>
              <Td>{j.workspace_name || (j.workspace_id ?? '')}</Td>
              <Td>{j.version ?? ''}</Td>
              <Td title={j.result || ''}><Text noOfLines={1}>{j.result || ''}</Text></Td>
              <Td>{j.create_time ? new Date(j.create_time).toLocaleString() : ''}</Td>
              <Td>{j.update_time ? new Date(j.update_time).toLocaleString() : ''}</Td>
              <Td>
                <HStack spacing={2}>
                  <Tooltip label="visibility"><Select size="xs" width="auto" value={j.visibility ?? 1} onChange={(e)=>doChangeVisibility(j.id, parseInt(e.target.value))}>
                    <option value={0}>hide</option>
                    <option value={1}>visible</option>
                    <option value={2}>visible in workspace</option>
                  </Select></Tooltip>
                  {(j.status >= 0) && (
                    <Tooltip label="terminate"><Button size="xs" variant="outline" onClick={()=>doTerminate(j.id)}> <i className="fa-solid fa-stop"></i> </Button></Tooltip>
                  )}
                  {(j.status <= 0 || j.status < 1) && (
                    <>
                      <Tooltip label="rerun (clean)"><Button size="xs" variant="outline" colorScheme="red" onClick={()=>doRerun(j.id, false)}><i className="fa-solid fa-rotate-right"></i></Button></Tooltip>
                      <Tooltip label="rerun in-situ"><Button size="xs" variant="outline" colorScheme="red" onClick={()=>doRerun(j.id, true)}><i className="fa-solid fa-arrows-rotate"></i></Button></Tooltip>
                    </>
                  )}
                  {(j.status !== 0 && j.status !== 1) && (
                    <Tooltip label="Mark failed"><Button size="sm" variant="outline" colorScheme="red" onClick={async()=>{
                      try {
                        const res = await apiPost(`/jobs/${j.id}/mark-wrong/`)
                        if (res.ok) { notify('marked as failed', 'success'); fetchAndReplaceJob(j.id) } else { notify(await extractError(res), 'error') }
                      } catch (e: any) { notify(e?.message || 'request failed', 'error') }
                    }}><i className="fa-solid fa-circle-xmark"></i></Button></Tooltip>
                  )}
                  {([ -1, -3, 2 ].includes(j.status)) && (
                    <Tooltip label="Resume from step"><Button size="sm" variant="outline" onClick={()=>{ setOpenModal({ type: 'resume', job: j }) }}><i className="fa-solid fa-rotate"></i></Button></Tooltip>
                  )}
                  <Tooltip label="Comments / memo"><Button size="xs" variant="outline" colorScheme="blue" onClick={()=>{/* handled elsewhere */}}><i className="fa-solid fa-comment-dots"></i></Button></Tooltip>
                  <Tooltip label="history"><Button size="xs" variant="outline" colorScheme="blue" onClick={()=>showHistory(j)}><i className="fa-solid fa-clock-rotate-left"></i></Button></Tooltip>
                  <Tooltip label="delete"><Button size="xs" variant="outline" colorScheme="blue" onClick={()=>doDeleteJob(j.id)}><i className="fa-solid fa-trash"></i></Button></Tooltip>
                </HStack>
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
    </Box>
  )
}

function JobCards(props: {
  results: Job[]
  isSelected: (id: number)=>boolean
  toggleSelect: (id: number)=>void
  toggleSelectAllCurrent: ()=>void
  clearSelection: ()=>void
  doChangeVisibility: (id: number, vis: number)=>void
  doRerun: (id: number, insitu: boolean)=>void
  doLockToggle: (id: number)=>void
  showFiles: (job: Job)=>void
  showLog: (job: Job, type: 'out'|'err')=>void
  showHistory: (job: Job)=>void
  doDeleteJob: (id: number)=>void
  doTerminate: (id: number)=>void
  selectedIds: number[]
  bulkAction: (ids: number[], action: 'terminate'|'rerun_clean'|'rerun_insitu'|'delete') => void
  runners: {id:number; name:string}[]
  workspaces: {id:number; name:string}[]
  expEnableRunner: boolean
  apiPatch: typeof import('../lib/api').apiPatch
  notify: (msg: string, type?: 'success'|'error')=>void
  fetchAndReplaceJob: (id: number)=>Promise<void>
  statusMap: Map<number, string>
  setEditValue: (v: string)=>void
  setOpenModal: (v: any)=>void
  setModalError: (v: string | null)=>void
  setModalLoading: (v: boolean)=>void
  setDependentsResults: (rows: Job[])=>void
  setDependenciesResults: (rows: Job[])=>void
}) {
  const {
    results, isSelected, toggleSelect, toggleSelectAllCurrent, clearSelection, doChangeVisibility, doRerun, doLockToggle,
    showFiles, showLog, showHistory, doDeleteJob, doTerminate, selectedIds, bulkAction, runners, workspaces, expEnableRunner, apiPatch,
    notify, fetchAndReplaceJob, statusMap, setEditValue, setOpenModal, setModalError, setModalLoading, setDependentsResults, setDependenciesResults,
  } = props
  const [shortcutsConfig, setShortcutsConfig] = useState<{ [protocolId: number]: Array<{ label: string; href_template: string; params_template?: string }> }>({})
  const [sharedShortcuts, setSharedShortcuts] = useState<Array<{ label: string; href_template: string; params_template?: string }>>([])
  useEffect(() => {
    let mounted = true
    ;(async () => {
      try {
        // load all active shortcuts in one call (server can paginate, keep page_size large if supported)
        const res = await apiGet('/shortcuts/?active=1&page_size=500')
        if (!res.ok) return
        const data = await res.json()
        const rows = Array.isArray(data) ? data : (data.results || [])
        const map: { [k: number]: Array<{ label: string; href_template: string; params_template?: string }> } = {}
        const shared: Array<{ label: string; href_template: string; params_template?: string }> = []
        for (const r of rows) {
          if (r.protocol === null || typeof r.protocol === 'undefined') {
            shared.push({ label: String(r.label || ''), href_template: String(r.href_template || ''), params_template: r.params_template || '' })
            continue
          }
          const pid = Number(r.protocol)
          if (!map[pid]) map[pid] = []
          map[pid].push({ label: String(r.label || ''), href_template: String(r.href_template || ''), params_template: r.params_template || '' })
        }
        if (mounted) { setShortcutsConfig(map); setSharedShortcuts(shared) }
      } catch (e: any) { console.debug('[Shortcuts] load error', e?.message || e) }
    })()
    return () => { mounted = false }
  }, [])
  function buildShortcuts(job: Job): Array<{ label: string; href: string }> {
    const pid = Number(job.protocol)
    const out: Array<{ label: string; href: string }> = []
    const items = [...(sharedShortcuts || []), ...(shortcutsConfig[pid] || [])]
    for (const it of items) {
      let href = it.href_template.replace('{id}', String(job.id))
      if (it.params_template && it.params_template.trim()) {
        const extra = it.params_template.replace('{id}', String(job.id))
        if (extra.startsWith('?') || extra.startsWith('&')) href += extra
        else if (extra.startsWith('/')) href += extra
        else href += (href.includes('?') ? '&' : '?') + extra
      }
      out.push({ label: it.label, href })
    }
    return out
  }
  const CardHead = React.memo(function CardHead({ j }: { j: Job }) {
    return (
      <Flex align="flex-start" justify="space-between">
        <Box>
          <Flex align="center" gap={2} fontSize="sm">
            <input type="checkbox" checked={isSelected(j.id)} onChange={()=>toggleSelect(j.id)} />
            <Text opacity={0.7}>#{j.id}</Text>
            <ButtonGroup variant="outline" isAttached>
              {j.visibility !== 0 && (
                <Tooltip label="Hide"><IconButton size="xs" aria-label="hide" title="hide" onClick={()=>doChangeVisibility(j.id, 0)} icon={<i className="fas fa-ban"></i>} /></Tooltip>
              )}
              {j.visibility !== 2 && (
                <Tooltip label="Visible in workspace"><IconButton size="xs" aria-label="visible in workspace" title="visible in workspace" onClick={()=>doChangeVisibility(j.id, 2)} icon={<i className="fa-solid fa-eye-slash"></i>} /></Tooltip>
              )}
              {j.visibility !== 1 && (
                <Tooltip label="Visible"><IconButton size="xs" aria-label="Visible" title="Visible" onClick={()=>doChangeVisibility(j.id, 1)} icon={<i className="fa-solid fa-eye"></i>} /></Tooltip>
              )}
              <Tooltip label={(j.locked ? 1 : 0) ? 'Unlock' : 'Lock'}><IconButton size="xs" aria-label={(j.locked ? 1 : 0) ? 'unlock' : 'lock'} onClick={()=>doLockToggle(j.id)} icon={(j.locked ? 1 : 0) ? <i className="fa-solid fa-lock-open"></i> : <i className="fa-solid fa-lock"></i>} /></Tooltip>
              <Tooltip label="Clone this job"><IconButton aria-label="clone" size="xs" variant="outline" onClick={()=>window.open(`/jobs/new?clone=${j.id}`, '_blank', 'noopener,noreferrer')} icon={<i className="fa-regular fa-clone"></i>} /></Tooltip>
              <Tooltip label="Dependents"><IconButton aria-label="dependents" size="xs" variant="outline" onClick={async()=>{
                setModalError(null)
                setModalLoading(true)
                setOpenModal({ type: 'dependents', job: j })
                setDependentsResults([])
                try {
                  const res = await apiGet(`/jobs/${j.id}/dependents/?depth=1&page_size=200`)
                  if (!res.ok) {
                    setModalError(await extractError(res))
                  } else {
                    const data = await res.json()
                    const rows = Array.isArray(data) ? data : (data.results || [])
                    setDependentsResults(rows || [])
                  }
                } catch (e:any) {
                  setModalError(e?.message || 'failed to load dependents')
                } finally {
                  setModalLoading(false)
                }
              }} icon={<i className="fa-solid fa-diagram-project"></i>} /></Tooltip>
              <Tooltip label="Dependencies"><IconButton aria-label="dependencies" size="xs" variant="outline" onClick={async()=>{
                setModalError(null)
                setModalLoading(true)
                setOpenModal({ type: 'dependencies', job: j })
                setDependenciesResults([])
                try {
                  const res = await apiGet(`/jobs/${j.id}/dependencies/?depth=1&page_size=200`)
                  if (!res.ok) {
                    setModalError(await extractError(res))
                  } else {
                    const data = await res.json()
                    const rows = Array.isArray(data) ? data : (data.results || [])
                    setDependenciesResults(rows || [])
                  }
                } catch (e:any) {
                  setModalError(e?.message || 'failed to load dependencies')
                } finally {
                  setModalLoading(false)
                }
              }} icon={<i className="fa-solid fa-diagram-next"></i>} /></Tooltip>
              {(() => { const links = buildShortcuts(j); return links.length ? (
                <Tooltip label="Shortcuts"><Menu>
                  <MenuButton as={IconButton} size="xs" aria-label="shortcuts" icon={<i className="fa-solid fa-ellipsis"></i>} variant="outline" />
                  <Portal>
                    <MenuList zIndex={1500}>
                      {links.map((l, idx) => (
                        <MenuItem as="a" key={idx} href={l.href} target="_blank" rel="noopener noreferrer">{l.label}</MenuItem>
                      ))}
                    </MenuList>
                  </Portal>
                </Menu></Tooltip>
              ) : null })()}
            </ButtonGroup>
          </Flex>
          <Heading size="md" mt={2}>{j.job_name}</Heading>
        </Box>
        <Text textStyle="xl" fontWeight="bold"><StatusBadge n={j.status} label={statusMap.get(j.status) || String(j.status)} /></Text>
      </Flex>
    )
  })
  const CardBody = React.memo(function CardBody({ j }: { j: Job }) {
    return (
      <Box opacity={0.8} h="290px" overflowY="auto">
        <Box title={String(j.protocol)+' - '+j.protocol_ver}><Text as="b" className="field-label">Protocol</Text> <ChakraLink as={RouterLink} to={`/protocols?select=${encodeURIComponent(String(j.protocol))}`} target="_blank" rel="noopener noreferrer" color="inherit" textDecoration="none" _hover={{ textDecoration: 'underline' }}>{j.protocol_name || j.protocol}</ChakraLink></Box>
        <Box mt={1}>
          <Flex align="center" gap={2}>
            <Text as="b" className="field-label">Workspace</Text>
            <Select size="sm" width="auto" value={j.workspace_id ?? ''} onChange={async (e)=>{
              const val = e.target.value
              const payload = val ? { workspace: parseInt(val) } : { workspace: null }
              const res = await apiPatch(`/jobs/${j.id}/`, JSON.stringify(payload))
              if (res.ok) { notify('workspace updated', 'success'); fetchAndReplaceJob(j.id) } else { try { const d = await res.json(); notify(d?.detail || 'update failed', 'error') } catch { notify('update failed', 'error') } }
            }}>
              <option value="">(none)</option>
              {workspaces.map(w => <option key={w.id} value={String(w.id)}>{w.name}</option>)}
            </Select>
          </Flex>
        </Box>
        <Box mt={1}>
          <Text as="b" className="field-label">Parameters</Text>
            <Text
              fontFamily="mono"
              fontSize="sm"
              maxW="full"
              whiteSpace="pre-wrap"
              wordBreak="break-word"
              cursor={j.status === 1 ? "not-allowed" : "pointer"}
              opacity={j.status === 1 ? 0.6 : 1}
              _hover={j.status === 1 ? {} : { textDecoration: 'underline' }}
              onClick={j.status === 1 ? undefined : ()=>{ setEditValue(j.parameter || ''); setOpenModal({ type: 'edit_param', job: j }); setModalError(null) }}
            >
              {(j.parameter && j.parameter.trim()) ? j.parameter : '(empty)'}
            </Text>
        </Box>
        <Box mt={1}>
          <Text as="b" className="field-label">Input files</Text>
            <Text
              fontFamily="mono"
              fontSize="sm"
              maxW="full"
              whiteSpace="pre-wrap"
              wordBreak="break-word"
              cursor={j.status === 1 ? "not-allowed" : "pointer"}
              opacity={j.status === 1 ? 0.6 : 1}
              _hover={j.status === 1 ? {} : { textDecoration: 'underline' }}
              onClick={j.status === 1 ? undefined : ()=>{ setEditValue(j.input_file || ''); setOpenModal({ type: 'edit_input', job: j }); setModalError(null) }}
            >
              {(j.input_file && j.input_file.trim()) ? j.input_file : '(empty)'}
            </Text>
        </Box>
        <Box mt={1}><Text as="b" className="field-label">Results</Text> <ButtonGroup variant="outline" isAttached>
            <Tooltip label="Results"><Button size="sm" variant="outline" onClick={()=>showFiles(j)}><i className="fa-regular fa-folder-open"></i> {j.result || ''}</Button></Tooltip>
            <Tooltip label="Stdout"><Button size="sm" variant="outline" onClick={()=>showLog(j, 'out')}><i className="fa-solid fa-file-lines"></i></Button></Tooltip>
            <Tooltip label="Stderr"><Button size="sm" variant="outline" onClick={()=>showLog(j, 'err')}><i className="fa-solid fa-file-circle-exclamation"></i></Button></Tooltip>
            <Tooltip label="History"><Button size="sm" variant="outline" onClick={()=>showHistory(j)}><i className="fa-solid fa-code-commit"></i></Button></Tooltip>
            </ButtonGroup>
        </Box>
        {expEnableRunner && (
          <Box mt={1}>
            <Flex align="center" gap={2}>
              <Text as="b" className="field-label">Runner</Text>
              <Select size="sm" width="auto" value={j.slave ?? ''} onChange={async (e)=>{
                const val = e.target.value
                const payload = val ? { slave: parseInt(val) } : { slave: null }
                const res = await apiPatch(`/jobs/${j.id}/`, JSON.stringify(payload))
                if (res.ok) { notify('runner updated', 'success'); fetchAndReplaceJob(j.id) } else { notify(await (async(r)=>{ try{ const d=await r.json(); return (d?.detail||d?.info||JSON.stringify(d)) }catch{ try{const t=await r.text(); return t||`${r.status}`}catch{return `${r.status}`}} })(res), 'error') }
              }}>
                <option value="">(none)</option>
                {runners.map(r => <option key={r.id} value={String(r.id)}>{r.name}</option>)}
              </Select>
            </Flex>
          </Box>
        )}
        <Box mt={1}><Text as="b" className="field-label">Created</Text> <Text as="span" fontSize="sm" opacity={0.8}>{j.create_time ? new Date(j.create_time).toLocaleString() : ''}</Text></Box>
        <Box mt={1}><Text as="b" className="field-label">Updated</Text> <Text as="span" fontSize="sm" opacity={0.8}>{j.update_time ? new Date(j.update_time).toLocaleString() : ''}</Text></Box>
      </Box>
    )
  })
  const CardFoot = React.memo(function CardFoot({ j }: { j: Job }) {
    return (
      <Flex flexWrap="wrap" gap={2} justify="center">
        <ButtonGroup isAttached>
        {(j.status >= 0) && (
          <Tooltip label="Terminate"><Button size="sm" colorScheme="red" onClick={()=>doTerminate(j.id)}><i className="fa-solid fa-stop"></i></Button></Tooltip>
        )}
        {(j.status <= 0 || j.status < 1) && (
          <>
            <Tooltip label="Rerun (clean)"><Button size="sm" colorScheme="orange" onClick={()=>doRerun(j.id, false)}><i className="fa-solid fa-rotate-right"></i></Button></Tooltip>
            {/* <Tooltip label="Rerun (inplace)"><Button size="sm" colorScheme="yellow" onClick={()=>doRerun(j.id, true)}><i className="fa-solid fa-arrows-rotate"></i></Button></Tooltip> */}
          </>
        )}
        {(j.status !== 0 && j.status !== 1) && (
          <Tooltip label="Mark failed"><Button size="sm" colorScheme="yellow" onClick={async()=>{
            try {
              const res = await apiPost(`/jobs/${j.id}/mark-wrong/`)
              if (res.ok) { notify('marked as failed', 'success'); fetchAndReplaceJob(j.id) } else { notify(await extractError(res), 'error') }
            } catch (e: any) { notify(e?.message || 'request failed', 'error') }
          }}><i className="fa-solid fa-triangle-exclamation"></i></Button></Tooltip>
        )}
        {([ -1, -3, 2 ].includes(j.status)) && (
          <Tooltip label="Resume from step"><Button size="sm" onClick={()=>{ setOpenModal({ type: 'resume', job: j }) }}><i className="fa-solid fa-timeline"></i></Button></Tooltip>
        )}
        <Tooltip label="Comments / memo"><Button size="sm" colorScheme="blue" onClick={()=>{ setEditValue(j.comments || ''); setOpenModal({ type: 'edit_comments', job: j }) }}><i className="fa-solid fa-comment-dots"></i></Button></Tooltip>
        <Tooltip label="Delete"><Button size="sm" colorScheme="red" onClick={()=>doDeleteJob(j.id)}><i className="fa-solid fa-trash"></i></Button></Tooltip>
        </ButtonGroup>
      </Flex>
    )
  })
  return (
    <>
      <Flex align="center" gap={2} mb={3} p={2} borderWidth="1px" borderColor="gray.200" rounded="md" bg="white">
        <Button size="sm" variant="outline" onClick={toggleSelectAllCurrent}>select all</Button>
        <Button size="sm" variant="outline" onClick={clearSelection}>clear</Button>
        {selectedIds && selectedIds.length > 0 && (
          <>
            <Box fontSize="sm" ml={2}>selected {selectedIds.length}</Box>
            <Button size="sm" variant="outline" onClick={()=>bulkAction(selectedIds, 'terminate')}>terminate</Button>
            <Button size="sm" variant="outline" onClick={()=>bulkAction(selectedIds, 'rerun_clean')}>rerun</Button>
            <Button size="sm" variant="outline" onClick={()=>bulkAction(selectedIds, 'rerun_insitu')}>rerun in-situ</Button>
            <Button size="sm" colorScheme="red" variant="outline" onClick={()=>bulkAction(selectedIds, 'delete')}>delete</Button>
          </>
        )}
      </Flex>
      <SimpleGrid spacing={6} columns={{ base: 1, sm: 2, lg: 3 }}>
      {results.map(j => (
        <Box key={j.id} borderWidth="1px" borderRadius="md" p="3" boxShadow="sm" borderColor={j.status === -3 ? 'red.300' : 'gray.200'} _hover={{ boxShadow: 'lg', borderColor: j.status === -3 ? 'red.400' : 'green.300' }}>
          <Box data-card-head>
            <CardHead j={j} />
          </Box>
          <Box data-card-body mt={2}>
            <CardBody j={j} />
          </Box>
          <Box data-card-foot mt={3}>
            <CardFoot j={j} />
          </Box>
        </Box>
      ))}
      </SimpleGrid>
    </>
  )
}

export default function JobMonitorPage() {
  const toast = useToast()
  const location = useLocation()
  const navigate = useNavigate()
  useEffect(() => { document.title = 'Job Status – BioQueue' }, [])
  const [keywords, setKeywords] = useState('')
  const [jobNameNot, setJobNameNot] = useState('')
  const [parameter, setParameter] = useState('')
  const [parameterNot, setParameterNot] = useState('')
  const [inputFile, setInputFile] = useState('')
  const [inputFileNot, setInputFileNot] = useState('')
  const [protocolId, setProtocolId] = useState('')
  const [protocolName, setProtocolName] = useState('')
  const [protocolNameNot, setProtocolNameNot] = useState('')
  const [workspaceId, setWorkspaceId] = useState('')
  const [workspaceName, setWorkspaceName] = useState('')
  const [workspaceNameNot, setWorkspaceNameNot] = useState('')
  const [statusText, setStatusText] = useState('')
  const [statusNotText, setStatusNotText] = useState('')
  const [mode, setMode] = useState<'all'|'any'>('all')
  const [statusChoices, setStatusChoices] = useState<{ value: number; label: string }[]>([
    { value: -3, label: 'Wrong' },
    { value: -2, label: 'ResourceLock' },
    { value: -1, label: 'Finished' },
    { value: 0, label: 'Waiting' },
    { value: 1, label: 'Running' },
    { value: 2, label: 'Interrupted' },
  ])
  const statusMap = useMemo(() => new Map(statusChoices.map(s => [s.value, s.label])), [statusChoices])
  const [statusSel, setStatusSel] = useState<number[]>([])
  const [statusNotSel, setStatusNotSel] = useState<number[]>([])
  const [idText, setIdText] = useState('')
  const [idNotText, setIdNotText] = useState('')
  const [results, setResults] = useState<Job[]>([])
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(12)
  const [totalCount, setTotalCount] = useState(0)
  const [autoRefresh, setAutoRefresh] = useState(true)
  // const [isHoveringActions, setIsHoveringActions] = useState(false)
  const totalPages = Math.max(1, Math.ceil((totalCount || 0) / (pageSize || 1)))
  const [protocols, setProtocols] = useState<{id:number; name:string}[]>([])
  const [workspaces, setWorkspaces] = useState<{id:number; name:string}[]>([])
  const [protocolFilter, setProtocolFilter] = useState('')
  const [workspaceFilter, setWorkspaceFilter] = useState('')
  const [loadingProtocols, setLoadingProtocols] = useState(false)
  const [loadingWorkspaces, setLoadingWorkspaces] = useState(false)
  const [viewMode, setViewMode] = useState<'table'|'cards'>('cards')
  const [nameOrIdInput, setNameOrIdInput] = useState('')
  const [showProtoDD, setShowProtoDD] = useState(false)
  const [showWsDD, setShowWsDD] = useState(false)
  const [showStatusDD, setShowStatusDD] = useState(false)
  const [showStatusNotDD, setShowStatusNotDD] = useState(false)
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false)
  const [runners, setRunners] = useState<{id:number; name:string}[]>([])
  const expEnableRunner = Boolean(import.meta.env.VITE_EXPERIMENTAL_RUNNER)

  // modal state
  const [openModal, setOpenModal] = useState<null | { type: 'files'|'stdout'|'stderr'|'history'|'edit_param'|'edit_input'|'edit_comments'|'preview'|'dependents'|'dependencies'|'resume'; job: Job; trace?: string; name?: string }>(null)
  const [modalLoading, setModalLoading] = useState(false)
  const [modalError, setModalError] = useState<string | null>(null)
  const [dependentsResults, setDependentsResults] = useState<Job[]>([])
  const [dependenciesResults, setDependenciesResults] = useState<Job[]>([])
  const [jobFiles, setJobFiles] = useState<JobFile[]>([])
  const [jobFilesTotal, setJobFilesTotal] = useState<number>(0)
  const [jobFilesHasMore, setJobFilesHasMore] = useState<boolean>(false)
  const [filesFilter, setFilesFilter] = useState('')
  const [logContent, setLogContent] = useState('')
  const [historyHtml, setHistoryHtml] = useState('')
  const [previewUrl, setPreviewUrl] = useState<string>('')
  const [previewMode, setPreviewMode] = useState<'iframe'|'text'|'img'>('iframe')
  const [previewText, setPreviewText] = useState<string>('')
  const [editValue, setEditValue] = useState('')
  const editModalSetValueRef = useRef<null | ((updater: (prev: string)=>string)=>void)>(null)
  const registerEditSetter = useCallback((setter: ((updater: (prev: string)=>string)=>void) | null) => {
    editModalSetValueRef.current = setter
  }, [])
  const [resumePoint, setResumePoint] = useState<number>(0)
  const [resumeMax, setResumeMax] = useState<number>(0)
  const [resumeSteps, setResumeSteps] = useState<Array<{ id: number; software: string; parameter: string; step_order: number }>>([])
  const [showJobResultsPicker, setShowJobResultsPicker] = useState(false)
  const [filesSortField, setFilesSortField] = useState<'name'|'size'|'created'>('name')
  const [filesSortOrder, setFilesSortOrder] = useState<'asc'|'desc'>('asc')
  const visibleJobFiles = useMemo(() => {
    const q = (filesFilter || '').trim().toLowerCase()
    if (!q) return jobFiles
    return jobFiles.filter(f => f.name.toLowerCase().includes(q))
  }, [filesFilter, jobFiles])
  const filesObserverRef = useRef<IntersectionObserver | null>(null)
  const filesContainerRef = useRef<HTMLDivElement | null>(null)
  const filesSentinelRef = useRef<HTMLDivElement | null>(null)
  const isReadingFromURL = useRef<boolean>(false)
  // using module-scope formatBytes in FilesTable

  function notify(msg: string, type: 'success'|'error' = 'error', ms = 3000) {
    toast({ title: msg, status: type, duration: ms, isClosable: true, position: 'bottom-right' })
  }

  function resetModalState() {
    try {
      if (previewUrl && previewUrl.startsWith('blob:')) URL.revokeObjectURL(previewUrl)
    } catch {}
    setOpenModal(null)
    setModalLoading(false)
    setModalError(null)
    setJobFiles([])
    setJobFilesTotal(0)
    setJobFilesHasMore(false)
    setFilesFilter('')
    setLogContent('')
    setHistoryHtml('')
    setPreviewUrl('')
    setPreviewText('')
    setEditValue('')
    setDependentsResults([])
    setDependenciesResults([])
  }

  const qs = useMemo(() => {
    const p = new URLSearchParams()
    if (keywords.trim()) p.set('job_name', keywords.trim())
    if (jobNameNot.trim()) p.set('job_name_not', jobNameNot.trim())
    if (parameter.trim()) p.set('parameter', parameter.trim())
    if (parameterNot.trim()) p.set('parameter_not', parameterNot.trim())
    if (inputFile.trim()) p.set('input_file', inputFile.trim())
    if (inputFileNot.trim()) p.set('input_file_not', inputFileNot.trim())
    if (protocolId.trim()) p.set('protocol', protocolId.trim())
    if (protocolName.trim()) p.set('protocol_name', protocolName.trim())
    if (protocolNameNot.trim()) p.set('protocol_name_not', protocolNameNot.trim())
    if (workspaceId.trim()) p.set('workspace', workspaceId.trim())
    if (workspaceName.trim()) p.set('workspace_name', workspaceName.trim())
    if (workspaceNameNot.trim()) p.set('workspace_name_not', workspaceNameNot.trim())
    if (statusText.trim()) p.set('status', statusText.trim())
    if (statusNotText.trim()) p.set('status_not', statusNotText.trim())
    if (idText.trim()) p.set('id', idText.trim())
    if (idNotText.trim()) p.set('id_not', idNotText.trim())
    if (mode !== 'all') p.set('mode', mode)
    p.set('page', String(page))
    p.set('page_size', String(pageSize))
    return p.toString()
  }, [keywords, jobNameNot, parameter, parameterNot, inputFile, inputFileNot, protocolId, protocolName, protocolNameNot, workspaceId, workspaceName, workspaceNameNot, statusText, statusNotText, idText, idNotText, mode, page, pageSize])

  // write current filters to URL
  useEffect(() => {
    if (isReadingFromURL.current) {
      // Skip URL update if we're currently reading from URL
      return
    }
    const next = `?${qs}`
    if (next !== location.search) {
      navigate({ search: next }, { replace: true })
    }
  }, [qs])

  // read filters from URL on navigation (e.g., back/forward or external link)
  useEffect(() => {
    isReadingFromURL.current = true

    const sp = new URLSearchParams(location.search || '')
    const kw = sp.get('job_name') || ''
    if (kw !== keywords) setKeywords(kw)
    const kwNot = sp.get('job_name_not') || ''
    if (kwNot !== jobNameNot) setJobNameNot(kwNot)
    const param = sp.get('parameter') || ''
    if (param !== parameter) setParameter(param)
    const paramNot = sp.get('parameter_not') || ''
    if (paramNot !== parameterNot) setParameterNot(paramNot)
    const infile = sp.get('input_file') || ''
    if (infile !== inputFile) setInputFile(infile)
    const infileNot = sp.get('input_file_not') || ''
    if (infileNot !== inputFileNot) setInputFileNot(infileNot)
    const proto = sp.get('protocol') || ''
    if (proto !== protocolId) setProtocolId(proto)
    const protoName = sp.get('protocol_name') || ''
    if (protoName !== protocolName) setProtocolName(protoName)
    const protoNameNot = sp.get('protocol_name_not') || ''
    if (protoNameNot !== protocolNameNot) setProtocolNameNot(protoNameNot)
    const ws = sp.get('workspace') || ''
    if (ws !== workspaceId) setWorkspaceId(ws)
    const wsName = sp.get('workspace_name') || ''
    if (wsName !== workspaceName) setWorkspaceName(wsName)
    const wsNameNot = sp.get('workspace_name_not') || ''
    if (wsNameNot !== workspaceNameNot) setWorkspaceNameNot(wsNameNot)
    const st = sp.get('status') || ''
    if (st !== statusText) {
      setStatusText(st)
      const arr = st ? st.split(',').map(v=>parseInt(v,10)).filter(n=>!Number.isNaN(n)) : []
      setStatusSel(arr)
    }
    const stNot = sp.get('status_not') || ''
    if (stNot !== statusNotText) {
      setStatusNotText(stNot)
      const arr = stNot ? stNot.split(',').map(v=>parseInt(v,10)).filter(n=>!Number.isNaN(n)) : []
      setStatusNotSel(arr)
    }
    const ids = sp.get('id') || ''
    if (ids !== idText) setIdText(ids)
    const idsNot = sp.get('id_not') || ''
    if (idsNot !== idNotText) setIdNotText(idsNot)
    const m = sp.get('mode') || 'all'
    if (m !== mode && (m === 'all' || m === 'any')) setMode(m as 'all'|'any')
    const pg = (()=>{ const v = parseInt(sp.get('page') || '1', 10); return Number.isFinite(v) && v>0 ? v : 1 })()
    if (pg !== page) setPage(pg)
    const psz = (()=>{ const v = parseInt(sp.get('page_size') || '12', 10); return Number.isFinite(v) && v>0 ? v : 12 })()
    if (psz !== pageSize) setPageSize(psz)

    // Seed unified input from URL-derived pieces
    const combined = [kw, ids].filter(s => (s || '').trim()).join(' ').trim()
    if (combined !== nameOrIdInput) setNameOrIdInput(combined)

    // Use setTimeout to reset the flag after the current execution cycle
    setTimeout(() => {
      isReadingFromURL.current = false
    }, 0)
  }, [location.search])

  // Debounced parse of unified name/id input into keywords and idText
  useEffect(() => {
    if (isReadingFromURL.current) return
    const t = window.setTimeout(() => {
      const raw = (nameOrIdInput || '').trim()
      const tokens = raw.split(/[\s,]+/).filter(Boolean)
      const ids = tokens.filter(t=>/^\d+$/.test(t)).join(',')
      const names = tokens.filter(t=>!/^\d+$/.test(t)).join(' ')
      if (names !== keywords) setKeywords(names)
      if (ids !== idText) setIdText(ids)
    }, 250)
    return () => window.clearTimeout(t)
  }, [nameOrIdInput])

  async function runSearch(e?: React.FormEvent) {
    e?.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const res = await apiGet(`/jobs/search/?${qs}`)
      if (!res.ok) throw new Error(`${res.status}`)
      const data = await res.json()
      const rows = Array.isArray(data) ? data : (data.results || [])
      if (!Array.isArray(data)) {
        setTotalCount(parseInt(data.count || 0))
      }
      setResults(rows || [])
      setSelectedIds([])
    } catch (err: any) {
      setError(`request failed${err?.message ? `: ${err.message}` : ''}`)
    } finally {
      setLoading(false)
    }
  }

  async function fetchAndReplaceJob(jobId: number) {
    try {
      const res = await apiGet(`/jobs/${jobId}/`)
      if (!res.ok) return
      const data = await res.json()
      setResults(prev => prev.map(j => (j.id === jobId ? { ...j, ...data } : j)))
    } catch {}
  }

  function toggleSelect(id: number) {
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }
  function isSelected(id: number) {
    return selectedIds.includes(id)
  }
  function toggleSelectAllCurrent() {
    if (!results.length) return
    const currentPageIds = results.map(r => r.id)
    const allSelected = currentPageIds.every(id => selectedIds.includes(id))
    if (allSelected) {
      setSelectedIds(prev => prev.filter(id => !currentPageIds.includes(id)))
    } else {
      const set = new Set<number>(selectedIds)
      currentPageIds.forEach(id => set.add(id))
      setSelectedIds(Array.from(set))
    }
  }

  async function bulkAction(ids: number[], action: 'terminate'|'rerun_clean'|'rerun_insitu'|'delete') {
    if (!ids.length) return
    // confirm for destructive actions
    if (action === 'delete' && !confirm(`Delete ${ids.length} job(s)? This cannot be undone.`)) return
    if ((action === 'rerun_clean' || action === 'rerun_insitu') && !confirm(`Rerun ${ids.length} job(s)${action==='rerun_insitu'?' in-situ':''}?`)) return
    try {
      for (const id of ids) {
        if (action === 'terminate') {
          await apiPost(`/jobs/${id}/terminate/`)
          await fetchAndReplaceJob(id)
        } else if (action === 'rerun_clean') {
          await apiPost(`/jobs/${id}/rerun/`)
          await fetchAndReplaceJob(id)
        } else if (action === 'rerun_insitu') {
          await apiPost(`/jobs/${id}/rerun/?insitu=1`)
          await fetchAndReplaceJob(id)
        } else if (action === 'delete') {
          await apiDelete(`/jobs/${id}/`)
          setResults(prev => prev.filter(j => j.id !== id))
        }
      }
      notify('bulk operation completed', 'success')
    } catch (e: any) {
      notify(e?.message || 'bulk operation failed', 'error')
    } finally {
      setSelectedIds([])
    }
  }

  // async search for protocols
  useEffect(() => {
    let aborted = false
    ;(async () => {
      setLoadingProtocols(true)
      try {
        const res = await apiGet(`/protocols/?page_size=50${protocolFilter ? `&q=${encodeURIComponent(protocolFilter)}` : ''}`)
        const data = await res.json()
        if (!aborted) setProtocols(Array.isArray(data) ? data : (data.results || []))
      } catch {
        if (!aborted) setProtocols([])
      } finally {
        if (!aborted) setLoadingProtocols(false)
      }
    })()
    return () => { aborted = true }
  }, [protocolFilter])

  // async search for workspaces
  useEffect(() => {
    let aborted = false
    ;(async () => {
      setLoadingWorkspaces(true)
      try {
        const res = await apiGet(`/workspaces/?page_size=100${workspaceFilter ? `&q=${encodeURIComponent(workspaceFilter)}` : ''}`)
        const data = await res.json()
        if (!aborted) setWorkspaces(Array.isArray(data) ? data : (data.results || []))
      } catch {
        if (!aborted) setWorkspaces([])
      } finally {
        if (!aborted) setLoadingWorkspaces(false)
      }
    })()
    return () => { aborted = true }
  }, [workspaceFilter])

  // initial list
  useEffect(() => { runSearch() /* eslint-disable-line */ }, [])

  // auto-search when filter criteria change (but not during URL reading)
  useEffect(() => {
    if (isReadingFromURL.current) return
    // Debounce the search to avoid too many requests while typing
    const timeoutId = setTimeout(() => {
      if (!loading) runSearch()
    }, 300) // 300ms delay
    return () => clearTimeout(timeoutId)
  }, [
    keywords, jobNameNot, parameter, parameterNot, inputFile, inputFileNot,
    protocolId, protocolName, protocolNameNot, workspaceId, workspaceName, workspaceNameNot,
    statusText, statusNotText, idText, idNotText, mode
  ])

  useEffect(() => { if (!loading) runSearch() /* eslint-disable-line */ }, [page, pageSize])
  

  // periodic refresh for changing job status; pauses on interaction (modal/dropdowns)
  useEffect(() => {
    const paused = !autoRefresh || Boolean(openModal) || showProtoDD || showWsDD || showStatusDD
    if (paused) return
    const id = window.setInterval(() => {
      // avoid refreshing while actively typing in inputs
      const ae = document.activeElement as HTMLElement | null
      const typing = !!ae && ['INPUT','TEXTAREA','SELECT'].includes(ae.tagName)
      if (!loading && !document.hidden && !typing) runSearch()
    }, 30000)
    return () => window.clearInterval(id)
    // include qs so filters are respected when changed
  }, [autoRefresh, openModal, showProtoDD, showWsDD, showStatusDD, loading, qs])

  // refresh when tab becomes visible again
  useEffect(() => {
    const onVis = () => { if (!document.hidden && !loading) runSearch() }
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [qs, loading])

  // fetch canonical status choices once
  useEffect(() => {
    ;(async () => {
      try {
        const res = await apiGet('/jobs/status-choices/')
        if (!res.ok) return
        const data = await res.json()
        if (Array.isArray(data) && data.length) {
          setStatusChoices(data.map((d: any) => ({ value: Number(d.value), label: String(d.label) })))
        }
      } catch {}
    })()
  }, [])

  // experimental: fetch runners list
  useEffect(() => {
    if (!expEnableRunner) return
    ;(async () => {
      try {
        const res = await apiGet('/jobs/runners/')
        const data = await res.json()
        if (Array.isArray(data)) setRunners(data)
      } catch {}
    })()
  }, [expEnableRunner])

  async function doTerminate(id: number) {
    const res = await apiPost(`/jobs/${id}/terminate/`)
    if (res.ok) {
      notify('terminated', 'success')
      fetchAndReplaceJob(id)
    } else {
      notify(await extractError(res), 'error')
    }
  }
  async function doRerun(id: number, insitu = false) {
    if (!confirm(`Rerun this job${insitu ? ' in-situ' : ' (clean)'}?`)) return
    const res = await apiPost(`/jobs/${id}/rerun/${insitu ? '?insitu=1' : ''}`)
    if (res.ok) {
      notify('rerun requested', 'success')
      fetchAndReplaceJob(id)
    } else {
      notify(await extractError(res), 'error')
    }
  }
  async function doDeleteJob(id: number) {
    if (!confirm('Delete this job? This cannot be undone.')) return
    const res = await apiDelete(`/jobs/${id}/`)
    if (res.ok) {
      notify('job deleted', 'success')
      setResults(prev => prev.filter(j => j.id !== id))
    } else {
      notify(await extractError(res), 'error')
    }
  }
  async function doLockToggle(id: number) {
    const res = await apiPost(`/jobs/${id}/lock/`)
    if (res.ok) {
      notify('lock state updated', 'success')
      fetchAndReplaceJob(id)
    } else {
      notify(await extractError(res), 'error')
    }
  }

  async function doChangeVisibility(id: number, vis: number) {
    const res = await apiPost(`/jobs/${id}/visibility/`, JSON.stringify({ visibility: vis }))
    if (res.ok) {
      notify('visibility updated', 'success')
      fetchAndReplaceJob(id)
    } else {
      notify(await extractError(res), 'error')
    }
  }

  async function showFiles(job: Job, sort: 'name'|'size'|'created' = filesSortField, order: 'asc'|'desc' = filesSortOrder) {
    setOpenModal({ type: 'files', job })
    setModalLoading(true)
    setModalError(null)
    setJobFiles([])
    setFilesFilter('')
    // reset offset implicitly by clearing list
    setFilesSortField(sort)
    setFilesSortOrder(order)
    try {
      const res = await apiGet(`/jobs/${job.id}/files/?limit=50&offset=0&sort=${encodeURIComponent(sort)}&order=${encodeURIComponent(order)}`)
      const data = await res.json()
      if (Array.isArray(data)) {
        setJobFiles(data)
        setJobFilesTotal(data.length)
        setJobFilesHasMore(false)
        // legacy shape returns full list; no more pages
      } else {
        setJobFiles(Array.isArray(data.items) ? data.items : [])
        setJobFilesTotal(Number(data.total || 0))
        setJobFilesHasMore(Boolean(data.has_more))
        // new shape returns pagination info; offset tracked via jobFiles.length
      }
    } catch (e: any) {
      setModalError(e?.message || 'failed to load files')
    } finally {
      setModalLoading(false)
    }
  }

  async function loadMoreFiles() {
    if (!openModal || openModal.type !== 'files') return
    const job = openModal.job
    const container = filesContainerRef.current
    const prevScrollTop = container ? container.scrollTop : 0
    const prevHeight = container ? container.scrollHeight : 0
    setModalLoading(true)
    setModalError(null)
    try {
      const currentOffset = jobFiles.length
      const res = await apiGet(`/jobs/${job.id}/files/?limit=200&offset=${currentOffset}&sort=${encodeURIComponent(filesSortField)}&order=${encodeURIComponent(filesSortOrder)}`)
      const data = await res.json()
      if (!Array.isArray(data) && Array.isArray(data.items)) {
        setJobFiles(prev => [...prev, ...data.items])
        setJobFilesHasMore(Boolean(data.has_more))
        // offset advances implicitly via jobFiles.length
        // restore scroll so we stay at the same visual item after new content appended
        requestAnimationFrame(() => {
          const cont = filesContainerRef.current
          if (cont) {
            const added = cont.scrollHeight - prevHeight
            cont.scrollTop = prevScrollTop
            if (added > 0) {
              cont.scrollTop = prevScrollTop
            }
          }
        })
      } else if (Array.isArray(data)) {
        // legacy shape; nothing more to load
        setJobFilesHasMore(false)
      }
    } catch (e: any) {
      setModalError(e?.message || 'failed to load more files')
    } finally {
      setModalLoading(false)
    }
  }

  function toggleFilesSort(field: 'name'|'size'|'created') {
    const nextOrder: 'asc'|'desc' = (filesSortField === field && filesSortOrder === 'asc') ? 'desc' : 'asc'
    setFilesSortField(field)
    setFilesSortOrder(nextOrder)
    if (openModal?.type === 'files') {
      showFiles(openModal.job, field, nextOrder)
    }
  }
  // infinite scroll for files list
  useEffect(() => {
    if (!(openModal && openModal.type === 'files')) return
    const sentinel = filesSentinelRef.current
    if (!sentinel) return
    if (filesObserverRef.current) {
      filesObserverRef.current.disconnect()
      filesObserverRef.current = null
    }
    filesObserverRef.current = new IntersectionObserver((entries) => {
      const e = entries[0]
      if (e && e.isIntersecting && jobFilesHasMore && !modalLoading) {
        loadMoreFiles()
      }
    }, { root: filesContainerRef.current, rootMargin: '100px', threshold: 0.01 })
    filesObserverRef.current.observe(sentinel)
    return () => {
      if (filesObserverRef.current) {
        filesObserverRef.current.disconnect()
        filesObserverRef.current = null
      }
    }
  }, [openModal, jobFilesHasMore, modalLoading, jobFiles.length, filesSortField, filesSortOrder])
  const showLog = useCallback(async function (job: Job, type: 'out'|'err') {
    setOpenModal({ type: type === 'out' ? 'stdout' : 'stderr', job })
    setModalLoading(true)
    setModalError(null)
    setLogContent('')
    try {
      const res = await apiGet(`/jobs/${job.id}/logs/?type=${type}`)
      const contentType = res.headers.get('Content-Type') || ''
      if (contentType.includes('application/json')) {
        const data = await res.json()
        let out = ''
        if (typeof data === 'string') {
          out = data
        } else if (Array.isArray(data)) {
          out = data.join('\n')
        } else {
          out = JSON.stringify(data, null, 2)
        }
        setLogContent(out.replace(/\r\n/g, '\n'))
      } else {
        const txtRaw = await res.text()
        let txt = txtRaw
        const trimmed = txtRaw.trim()
        // handle json-encoded string like "line1\nline2"
        if ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
          try { txt = JSON.parse(trimmed) } catch {}
        }
        setLogContent((txt || '').replace(/\r\n/g, '\n'))
      }
    } catch (e: any) {
      setModalError(e?.message || 'failed to load log')
    } finally {
      setModalLoading(false)
    }
  }, [])
  const showHistory = useCallback(async function (job: Job) {
    setOpenModal({ type: 'history', job })
    setModalLoading(true)
    setModalError(null)
    setHistoryHtml('')
    try {
      const res = await apiGet(`/jobs/${job.id}/history/`)
      const contentType = res.headers.get('Content-Type') || ''
      if (contentType.includes('text/html')) {
        const html = await res.text()
        setHistoryHtml(html)
      } else {
        const data = await res.json()
        // render simple diff: + added (green), - removed (red)
        let html = ''
        for (const item of (Array.isArray(data) ? data : [])) {
          html += `<div class="font-mono text-sm"><ul class="list-none m-0 p-0"><li>operation: ${escapeHtml(item.operation)} (${escapeHtml(item.timestamp)})</li><li>protocol version: ${escapeHtml(String(item.protocol_ver||''))}</li></ul>`
          for (const e of (item.entries || [])) {
            if (!e.text) continue
            if (e.kind === 'added') {
              html += `<span class="text-green-600">+&nbsp;${'&nbsp;'.repeat((e.indent||0)*2)}${escapeHtml(e.text)}</span><br/>`
            } else if (e.kind === 'removed') {
              html += `<span class="text-red-600">-&nbsp;${'&nbsp;'.repeat((e.indent||0)*2)}${escapeHtml(e.text)}</span><br/>`
            }
          }
          html += `</div><hr class="my-2 border-gray-200 dark:border-gray-800"/>`
        }
        setHistoryHtml(html)
      }
    } catch (e: any) {
      setModalError(e?.message || 'failed to load history')
    } finally {
      setModalLoading(false)
    }
  }, [])
  const downloadFile = useCallback(async function (job: Job, trace: string) {
    const url = `/api/jobs/${job.id}/download/?trace=${encodeURIComponent(trace)}`
    window.open(url, '_blank')
  }, [])
  const previewFile = useCallback(async function (job: Job, trace: string, name: string) {
    setOpenModal({ type: 'preview', job, trace, name })
    setModalLoading(true)
    setModalError(null)
    // cleanup previous blob url if any
    if (previewUrl.startsWith('blob:')) {
      try { URL.revokeObjectURL(previewUrl) } catch {}
    }
    setPreviewUrl('')
    setPreviewText('')
    setPreviewMode('iframe')
    try {
      // fetch the content to avoid cross-origin iframe restrictions; then render via blob url or text
      const res = await apiGet(`/jobs/${job.id}/preview/?trace=${encodeURIComponent(trace)}`)
      const contentType = res.headers.get('Content-Type') || ''
      if (!res.ok) {
        throw new Error(await extractError(res))
      }
      if (contentType.includes('text/html') || contentType.includes('application/xhtml')) {
        const txt = await res.text()
        const blob = new Blob([txt], { type: 'text/html' })
        const url = URL.createObjectURL(blob)
        setPreviewUrl(url)
        setPreviewMode('iframe')
      } else if (contentType.startsWith('text/') || contentType.includes('application/json') || contentType.includes('application/xml')) {
        const txt = await res.text()
        setPreviewText(txt)
        setPreviewMode('text')
      } else if (contentType.startsWith('image/')) {
        const blob = await res.blob()
        const url = URL.createObjectURL(blob)
        setPreviewUrl(url)
        setPreviewMode('img')
      } else if (contentType.includes('application/pdf')) {
        const blob = await res.blob()
        const url = URL.createObjectURL(blob)
        setPreviewUrl(url)
        setPreviewMode('iframe')
      } else {
        // fallback: open in new window
        const url = `/api/jobs/${job.id}/preview/?trace=${encodeURIComponent(trace)}`
        setPreviewUrl(url)
        setPreviewMode('iframe')
      }
    } catch (e: any) {
      setModalError(e?.message || 'failed to preview file')
    } finally {
      setModalLoading(false)
    }
  }, [previewUrl])
  const deleteFile = useCallback(async function (job: Job, trace: string) {
    if (!confirm('Delete this file?')) return
    const res = await apiDelete(`/jobs/${job.id}/delete-file/?trace=${encodeURIComponent(trace)}`)
    if (res.ok) {
      notify('file deleted', 'success')
      showFiles(job)
    } else {
      notify(await extractError(res), 'error')
    }
  }, [notify, showFiles])

  const EditFieldModal = React.memo(function EditFieldModal({
    mode,
    initialValue,
    onSave,
    onCancel,
    registerSetter,
    disableParamEdit,
    onOpenResultsPicker,
  }: {
    mode: 'edit_param'|'edit_input'|'edit_comments'
    initialValue: string
    onSave: (value: string) => Promise<void>
    onCancel: () => void
    registerSetter?: (setter: ((updater: (prev: string)=>string) => void) | null) => void
    disableParamEdit?: boolean
    onOpenResultsPicker: () => void
  }) {
    const [val, setVal] = useState<string>(initialValue)
    useEffect(() => { setVal(initialValue) }, [initialValue, mode])
    useEffect(() => {
      if (!registerSetter) return
      const setter = (updater: (prev: string)=>string) => setVal(prev => updater(prev))
      registerSetter(setter)
      return () => { registerSetter(null) }
    }, [registerSetter])
    const isEditingDisabled = disableParamEdit && (mode === 'edit_param' || mode === 'edit_input')
    return (
      <Box>
        <Textarea
          value={val}
          onChange={(e)=>setVal(e.target.value)}
          rows={10}
          size="sm"
          resize="vertical"
          fontFamily="mono"
          isDisabled={isEditingDisabled}
        />
        {mode === 'edit_input' && (
          <Flex mt={2} gap={2}>
            <Button size="sm" variant="outline" onClick={onOpenResultsPicker} isDisabled={isEditingDisabled}>
              <i className="fa-regular fa-clone"></i>&nbsp;Insert from job results
            </Button>
          </Flex>
        )}
        <Flex mt={3} gap={2} justify="flex-end">
          <Button size="sm" variant="outline" onClick={onCancel}>Cancel</Button>
          <Button size="sm" colorScheme="blue" onClick={()=>onSave(val)} isDisabled={isEditingDisabled}>Save</Button>
        </Flex>
      </Box>
    )
  })

  // load resume info when resume modal opens
  useEffect(() => {
    (async () => {
      if (openModal && openModal.type === 'resume') {
        setModalLoading(true)
        setModalError(null)
        setResumePoint(0)
        setResumeMax(0)
        setResumeSteps([])
        try {
          const [jobRes, stepsRes] = await Promise.all([
            apiGet(`/jobs/${openModal.job.id}/`),
            apiGet(`/steps/?parent=${encodeURIComponent(String(openModal.job.protocol))}&page_size=1000`),
          ])
          let cur = 0
          if (jobRes.ok) {
            try { const data = await jobRes.json(); cur = Number(data?.resume || 0) } catch {}
          }
          let maxIdx = 0
          if (stepsRes.ok) {
            const data = await stepsRes.json()
            const rows = Array.isArray(data) ? data : (data.results || [])
            const items = (Array.isArray(rows) ? rows : []).map((r: any) => ({ id: Number(r.id), software: String(r.software || ''), parameter: String(r.parameter || ''), step_order: Number(r.step_order || 0) }))
            items.sort((a: any, b: any) => a.step_order - b.step_order || a.id - b.id)
            setResumeSteps(items)
            const count = items.length
            if (count > 0) maxIdx = Math.max(0, count - 1)
          }
          setResumeMax(maxIdx)
          setResumePoint(Math.max(0, Math.min(maxIdx, cur)))
        } catch (e: any) {
          setModalError(e?.message || 'failed to load resume info')
        } finally {
          setModalLoading(false)
        }
      }
    })()
  }, [openModal?.type, openModal?.job?.id])

  return (
    <div>
      <Heading as="h3" mb={4}>Job Status</Heading>
      <FiltersHeader
        nameOrIdInput={nameOrIdInput}
        setNameOrIdInput={setNameOrIdInput}
        jobNameNot={jobNameNot}
        setJobNameNot={(v: string)=>{ setJobNameNot(v); setPage(1) }}
        parameter={parameter}
        setParameter={(v: string)=>{ setParameter(v); setPage(1) }}
        parameterNot={parameterNot}
        setParameterNot={(v: string)=>{ setParameterNot(v); setPage(1) }}
        inputFile={inputFile}
        setInputFile={(v: string)=>{ setInputFile(v); setPage(1) }}
        inputFileNot={inputFileNot}
        setInputFileNot={(v: string)=>{ setInputFileNot(v); setPage(1) }}
        protocolId={protocolId}
        setProtocolId={(v: string)=>{ setProtocolId(v); setPage(1) }}
        protocolName={protocolName}
        setProtocolName={(v: string)=>{ setProtocolName(v); setPage(1) }}
        protocolNameNot={protocolNameNot}
        setProtocolNameNot={(v: string)=>{ setProtocolNameNot(v); setPage(1) }}
        workspaceId={workspaceId}
        setWorkspaceId={(v: string)=>{ setWorkspaceId(v); setPage(1) }}
        workspaceName={workspaceName}
        setWorkspaceName={(v: string)=>{ setWorkspaceName(v); setPage(1) }}
        workspaceNameNot={workspaceNameNot}
        setWorkspaceNameNot={(v: string)=>{ setWorkspaceNameNot(v); setPage(1) }}
        statusChoices={statusChoices}
        statusSel={statusSel}
        setStatusSel={setStatusSel}
        setStatusText={setStatusText}
        statusNotSel={statusNotSel}
        setStatusNotSel={setStatusNotSel}
        setStatusNotText={setStatusNotText}
        idNotText={idNotText}
        setIdNotText={(v: string)=>{ setIdNotText(v); setPage(1) }}
        mode={mode}
        setMode={(v: 'all'|'any')=>{ setMode(v); setPage(1) }}
        loading={loading}
        runSearch={runSearch}
        pageSize={pageSize}
        setPageSize={(n: number)=>{ setPageSize(n); setPage(1) }}
        setPage={setPage}
        viewMode={viewMode}
        setViewMode={setViewMode}
        autoRefresh={autoRefresh}
        setAutoRefresh={setAutoRefresh}
        selectedIdsCount={selectedIds.length}
        bulkAction={bulkAction}
        selectedIds={selectedIds}
        protocols={protocols}
        workspaces={workspaces}
        protocolFilter={protocolFilter}
        setProtocolFilter={setProtocolFilter}
        workspaceFilter={workspaceFilter}
        setWorkspaceFilter={setWorkspaceFilter}
        loadingProtocols={loadingProtocols}
        loadingWorkspaces={loadingWorkspaces}
        showProtoDD={showProtoDD}
        setShowProtoDD={setShowProtoDD}
        showWsDD={showWsDD}
        setShowWsDD={setShowWsDD}
        showStatusDD={showStatusDD}
        setShowStatusDD={setShowStatusDD}
        showStatusNotDD={showStatusNotDD}
        setShowStatusNotDD={setShowStatusNotDD}
        showAdvancedFilters={showAdvancedFilters}
        setShowAdvancedFilters={setShowAdvancedFilters}
      />
      {error && (
        <Box mb={3} p={3} borderRadius="md" border="1px" borderColor="red.300" bg="red.50" color="red.700" _dark={{ bg: "red.900/20", color: "red.300" }}>{error}</Box>
      )}
      {loading ? (
        <Flex align="center" gap={2} fontSize="sm" opacity={0.8} justify="center"><Spinner size="sm" /> loading…</Flex>
      ) : viewMode === 'table' ? (
        <JobTable
          results={results}
          selectedIds={selectedIds}
          isSelected={isSelected}
          toggleSelect={toggleSelect}
          toggleSelectAllCurrent={toggleSelectAllCurrent}
          statusMap={statusMap}
          doChangeVisibility={doChangeVisibility}
          doTerminate={doTerminate}
          doRerun={doRerun}
          doLockToggle={doLockToggle}
          showFiles={showFiles}
          showLog={showLog}
          showHistory={showHistory}
          doDeleteJob={doDeleteJob}
          notify={notify}
          fetchAndReplaceJob={fetchAndReplaceJob}
          setOpenModal={setOpenModal}
          setEditValue={setEditValue}
        />
      ) : (
        <JobCards
          results={results}
          isSelected={isSelected}
          toggleSelect={toggleSelect}
          toggleSelectAllCurrent={toggleSelectAllCurrent}
          clearSelection={()=>setSelectedIds([])}
          doChangeVisibility={doChangeVisibility}
          doRerun={doRerun}
          doLockToggle={doLockToggle}
          showFiles={showFiles}
          showLog={showLog}
          showHistory={showHistory}
          doDeleteJob={doDeleteJob}
          doTerminate={doTerminate}
          selectedIds={selectedIds}
          bulkAction={bulkAction}
          runners={runners}
          workspaces={workspaces}
          expEnableRunner={expEnableRunner}
          apiPatch={apiPatch}
          notify={notify}
          fetchAndReplaceJob={fetchAndReplaceJob}
          statusMap={statusMap}
          setEditValue={setEditValue}
          setOpenModal={setOpenModal}
          setModalError={setModalError}
          setModalLoading={setModalLoading}
          setDependentsResults={setDependentsResults}
          setDependenciesResults={setDependenciesResults}
        />
      )}
      <Flex mt={4} justify="center">
        <Pager page={page} totalPages={totalPages} loading={loading} onChange={(v)=>setPage(v)} />
      </Flex>

      <Modal isOpen={Boolean(openModal)} onClose={resetModalState} size={openModal?.type?.startsWith('edit_') || openModal?.type==='resume' ? '4xl' : '6xl'} scrollBehavior="inside">
        <ModalOverlay />
        <ModalContent>
          <ModalHeader fontSize="md">
            {openModal?.type === 'files' && `Files for job #${openModal?.job.id}`}
            {openModal?.type === 'preview' && `Preview: ${openModal?.name || ''}`}
            {openModal?.type === 'stdout' && `Stdout for job #${openModal?.job.id}`}
            {openModal?.type === 'stderr' && `Stderr for job #${openModal?.job.id}`}
            {openModal?.type === 'history' && `History for job #${openModal?.job.id}`}
            {openModal?.type === 'edit_param' && `Edit parameters for job #${openModal?.job.id}`}
            {openModal?.type === 'edit_input' && `Edit input files for job #${openModal?.job.id}`}
            {openModal?.type === 'edit_comments' && `Edit comments for job #${openModal?.job.id}`}
            {openModal?.type === 'dependents' && `Dependents for job #${openModal?.job.id}`}
            {openModal?.type === 'dependencies' && `Dependencies for job #${openModal?.job.id}`}
            {openModal?.type === 'resume' && `Resume job #${openModal?.job.id}`}
          </ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            {(modalLoading && (openModal?.type !== 'files' || jobFiles.length === 0)) && (
              <Flex align="center" gap={2} fontSize="sm" opacity={0.8} justify="center"><Spinner size="sm" /> loading…</Flex>
            )}
            {modalError && <Box mb={3} p={2} borderRadius="md" border="1px" borderColor="red.300" bg="red.50" color="red.700" _dark={{ bg: "red.900/20", color: "red.300" }}>{modalError}</Box>}
            {(openModal?.type === 'edit_param' || openModal?.type === 'edit_input' || openModal?.type === 'edit_comments') && (
              <EditFieldModal
                mode={openModal!.type}
                initialValue={editValue}
                registerSetter={registerEditSetter}
                onOpenResultsPicker={()=>setShowJobResultsPicker(true)}
                disableParamEdit={openModal!.job.status === 1}
                onCancel={()=>resetModalState()}
                onSave={async(val:string)=>{
                  if (!openModal) return
                  if ((openModal.type === 'edit_param' || openModal.type === 'edit_input') && openModal.job.status === 1) {
                    setModalError('Cannot edit parameters or input files while job is running')
                    return
                  }
                  setModalError(null)
                  setModalLoading(true)
                  try {
                    const payload = openModal.type === 'edit_param' ? { parameter: val } : openModal.type === 'edit_input' ? { input_file: val } : { comments: val }
                    const res = await apiPatch(`/jobs/${openModal.job.id}/`, JSON.stringify(payload))
                    if (res.ok) { notify('updated', 'success'); resetModalState(); runSearch() } else { notify(await extractError(res), 'error') }
                  } catch (e:any) {
                    setModalError(e?.message || 'update failed')
                  } finally {
                    setModalLoading(false)
                  }
                }}
              />
            )}
            {!modalError && openModal?.type === 'files' && (
              <Box data-files-container ref={filesContainerRef} maxH="70vh" overflowY="auto">
                <Box position="sticky" top={0} bg="white" zIndex={1} pb={2} pt={1}>
                  <Flex gap={2} align="center">
                    <Input size="sm" placeholder="filter files" value={filesFilter} onChange={(e)=>setFilesFilter(e.target.value)} flex="1" />
                    <Button size="sm" onClick={()=>{ /* live filter; button kept for consistency */ }}>Filter</Button>
                  </Flex>
                </Box>
                <FilesTable
                  files={visibleJobFiles}
                  sortField={filesSortField}
                  sortOrder={filesSortOrder}
                  onSort={toggleFilesSort}
                  onPreview={(f)=>previewFile(openModal!.job, f.trace, f.name)}
                  onDownload={(f)=>downloadFile(openModal!.job, f.trace)}
                  onDelete={(f)=>deleteFile(openModal!.job, f.trace)}
                />
                {modalLoading && jobFiles.length > 0 && (
                  <Box textAlign="center" mt={2}><Spinner size="sm" /></Box>
                )}
                <Box ref={filesSentinelRef} h="1px" />
                {jobFilesHasMore && (
                  <Box textAlign="center" mt={2} fontSize="sm" opacity={0.7}>{jobFiles.length} / {jobFilesTotal || '…'}</Box>
                )}
              </Box>
            )}
            {!modalLoading && !modalError && openModal?.type === 'preview' && (
              <Box w="full">
                <Box mb={2}>
                  <PreviewToolbar
                    onBack={()=>setOpenModal({ type: 'files', job: openModal!.job })}
                    onOpenNewWindow={()=>window.open(previewUrl || `/api/jobs/${openModal!.job.id}/preview/?trace=${encodeURIComponent(openModal!.trace!)}`, '_blank')}
                    onDownload={()=>downloadFile(openModal!.job, openModal!.trace!)}
                  />
                </Box>
                {previewMode === 'text' && (
                  <Box as="pre" w="full" h="70vh" overflow="auto" fontSize="sm" whiteSpace="pre-wrap" borderWidth="1px" rounded="md" p={2} bg="white" borderColor="gray.200">{previewText}</Box>
                )}
                {previewMode === 'img' && previewUrl && (
                  <Flex w="full" h="70vh" align="center" justify="center" overflow="auto">
                    <Image src={previewUrl} alt={openModal?.name || 'image'} maxW="100%" maxH="100%" />
                  </Flex>
                )}
                {previewMode === 'iframe' && previewUrl && (
                  <Box w="full" h="70vh">
                    <Box as="iframe" title="preview" src={previewUrl} w="full" h="full" border={0} />
                  </Box>
                )}
              </Box>
            )}
            {!modalLoading && !modalError && (openModal?.type === 'stdout' || openModal?.type === 'stderr') && (
              <Box as="pre" fontFamily="mono" whiteSpace="pre-wrap" fontSize="sm">{logContent}</Box>
            )}
            {!modalLoading && !modalError && openModal?.type === 'history' && (
              <Box fontSize="sm" maxW="none" dangerouslySetInnerHTML={{ __html: historyHtml }} />
            )}
            {!modalLoading && !modalError && openModal?.type === 'dependents' && (
              <JobTable
                results={dependentsResults}
                selectedIds={[]}
                isSelected={()=>false}
                toggleSelect={()=>{}}
                toggleSelectAllCurrent={()=>{}}
                statusMap={statusMap}
                doChangeVisibility={(id, vis)=>doChangeVisibility(id, vis)}
                doTerminate={(id)=>doTerminate(id)}
                doRerun={(id, insitu)=>doRerun(id, insitu)}
                doLockToggle={(id)=>doLockToggle(id)}
                showFiles={(job)=>showFiles(job)}
                showLog={(job, t)=>showLog(job, t)}
                showHistory={(job)=>showHistory(job)}
                doDeleteJob={(id)=>doDeleteJob(id)}
                notify={notify}
                fetchAndReplaceJob={fetchAndReplaceJob}
                setOpenModal={setOpenModal}
                setEditValue={setEditValue}
              />
            )}
            {!modalLoading && !modalError && openModal?.type === 'dependencies' && (
              <JobTable
                results={dependenciesResults}
                selectedIds={[]}
                isSelected={()=>false}
                toggleSelect={()=>{}}
                toggleSelectAllCurrent={()=>{}}
                statusMap={statusMap}
                doChangeVisibility={(id, vis)=>doChangeVisibility(id, vis)}
                doTerminate={(id)=>doTerminate(id)}
                doRerun={(id, insitu)=>doRerun(id, insitu)}
                doLockToggle={(id)=>doLockToggle(id)}
                showFiles={(job)=>showFiles(job)}
                showLog={(job, t)=>showLog(job, t)}
                showHistory={(job)=>showHistory(job)}
                doDeleteJob={(id)=>doDeleteJob(id)}
                notify={notify}
                fetchAndReplaceJob={fetchAndReplaceJob}
                setOpenModal={setOpenModal}
                setEditValue={setEditValue}
              />
            )}
            {!modalLoading && !modalError && openModal?.type === 'resume' && (
              <Box>
                <Box mb={3} fontSize="sm" opacity={0.8}>select a step index to roll back to</Box>
                <Box px={1} mb={2}>
                  <Slider min={0} max={resumeMax} step={1} value={Math.min(Math.max(0, resumePoint), resumeMax)} onChange={(v)=>setResumePoint(Number(v))}>
                    <SliderTrack><SliderFilledTrack /></SliderTrack>
                    <SliderThumb />
                  </Slider>
                  <Flex mt={2} justify="space-between" fontSize="sm">
                    <Text>0</Text>
                    <Text>index: {resumePoint}</Text>
                    <Text>{resumeMax}</Text>
                  </Flex>
                </Box>
                <Box mb={3} borderWidth="1px" borderColor="gray.200" rounded="md" p={2} bg="white">
                  {resumeSteps[resumePoint] ? (
                    <Box>
                      <Box fontWeight="semibold" mb={1}>step {resumePoint} (order {resumeSteps[resumePoint].step_order})</Box>
                      <Box>
                        <Box fontSize="sm" color="gray.600" mb={1}>software</Box>
                        <Box as="pre" fontFamily="mono" fontSize="sm" whiteSpace="pre-wrap">{resumeSteps[resumePoint].software}</Box>
                      </Box>
                      <Box mt={2}>
                        <Box fontSize="sm" color="gray.600" mb={1}>parameter</Box>
                        <Box as="pre" fontFamily="mono" fontSize="sm" whiteSpace="pre-wrap">{resumeSteps[resumePoint].parameter}</Box>
                      </Box>
                    </Box>
                  ) : (
                    <Box fontSize="sm" opacity={0.7}>no step information</Box>
                  )}
                </Box>
                <Flex align="center" gap={2}>
                  <Button size="sm" variant="outline" onClick={resetModalState}>Cancel</Button>
                  <Button size="sm" colorScheme="blue" onClick={async()=>{
                    try {
                      setModalLoading(true)
                      const res = await apiPost(`/jobs/${openModal!.job.id}/resume/`, JSON.stringify({ rollback_to: resumePoint }))
                      if (res.ok) { notify('resume requested', 'success'); resetModalState(); fetchAndReplaceJob(openModal!.job.id) } else { notify(await extractError(res), 'error') }
                    } catch (e: any) {
                      notify(e?.message || 'resume failed', 'error')
                    } finally {
                      setModalLoading(false)
                    }
                  }}>Resume</Button>
                </Flex>
              </Box>
            )}
          </ModalBody>
        </ModalContent>
      </Modal>

      <JobResultsPicker
        isOpen={showJobResultsPicker}
        onClose={()=>setShowJobResultsPicker(false)}
        onInsert={(tokens)=>{
          if (tokens.length) {
            const append = tokens.join(";")
            try {
              if (editModalSetValueRef.current) {
                editModalSetValueRef.current(prev => (prev ? prev + ";" : "") + append)
              }
            } catch {}
            setEditValue(prev => (prev ? prev + ";" : "") + append)
          }
        }}
      />
    </div>
  )
}


function statusLabel(n: number, override?: string): string {
  if (override) return override
  const map: Record<number, string> = {
    [-3]: 'Wrong',
    [-2]: 'ResourceLock',
    [-1]: 'Finished',
    0: 'Waiting',
    1: 'Running',
    2: 'Interrupted',
  }
  return map[n] ?? String(n)
}


function StatusBadge({ n, label: providedLabel }: { n: number, label?: string }) {
  const label = statusLabel(n, providedLabel)
  const icon = (() => {
    switch (n) {
      case -3: return <Text color="red"><i className="fa-solid fa-circle-xmark"></i></Text> // Wrong
      case -2: return <Text color="orange"><i className="fa-solid fa-hourglass-half"></i></Text> // ResourceLock
      case -1: return <Text color="green"><i className="fa-solid fa-circle-check"></i></Text> // Finished
      case 0: return <Text color="gray"><i className="fa-solid fa-clock"></i></Text> // Waiting
      case 1: return <Text color="blue.600"><i className="fa-solid fa-circle-play"></i></Text> // Running
      case 2: return <Text color="yellow"><i className="fa-solid fa-circle-pause"></i></Text> // Interrupted
      default: return <Text color="gray"><i className="fa-solid fa-circle"></i></Text>
    }
  })()
  return (
    <Box as="span" display="inline-flex" alignItems="center" title={label} aria-label={label}>{icon}</Box>
  )
}
