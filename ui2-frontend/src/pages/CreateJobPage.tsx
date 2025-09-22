import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Box, Button, Flex, FormControl, FormLabel, FormHelperText, Heading, Input, Modal, ModalBody, ModalCloseButton, ModalContent, ModalHeader, ModalOverlay, Spinner, Table, Tbody, Td, Th, Thead, Tr, Textarea, Tooltip, useToast, Menu, MenuButton, MenuList, MenuOptionGroup, MenuItemOption, Portal, Divider, SimpleGrid, Tag, Checkbox, Tabs, TabList, TabPanels, Tab, TabPanel, Alert, AlertIcon, AlertTitle, AlertDescription, ListItem, UnorderedList } from '@chakra-ui/react'
import { apiGet, apiPost } from '../lib/api'
import { formatBytes } from '../lib/format'
import JobResultsPicker from '../components/JobResultsPicker'

type ProtocolOption = { id: number; name: string }
type WorkspaceOption = { id: number; name: string }

export default function CreateJobPage() {
  useEffect(() => { document.title = 'New Job – BioQueue' }, [])
  const toast = useToast()
  const navigate = useNavigate()
  const location = useLocation()
  const cloneFrom = (location.state as any)?.cloneFrom as undefined | {
    job_name?: string
    protocol?: number
    parameter?: string
    input_file?: string
    workspace?: number | string | null
    comments?: string
  }

  const [jobName, setJobName] = useState(cloneFrom?.job_name ? `${cloneFrom.job_name}-copy` : '')
  const [protocolId, setProtocolId] = useState(cloneFrom?.protocol != null ? String(cloneFrom.protocol) : '')
  const [parameter, setParameter] = useState(cloneFrom?.parameter || '')
  const [inputFile, setInputFile] = useState(cloneFrom?.input_file || '')
  const [workspaceId, setWorkspaceId] = useState(
    cloneFrom?.workspace != null && cloneFrom.workspace !== '' ? String(cloneFrom.workspace) : ''
  )
  const [comments, setComments] = useState(cloneFrom?.comments || '')

  const [protocols, setProtocols] = useState<ProtocolOption[]>([])
  const [workspaces, setWorkspaces] = useState<WorkspaceOption[]>([])
  const [loadingOptions, setLoadingOptions] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [showProtoDD, setShowProtoDD] = useState(false)
  const [showWsDD, setShowWsDD] = useState(false)
  const [protocolFilter, setProtocolFilter] = useState('')
  const [workspaceFilter, setWorkspaceFilter] = useState('')
  const [runners, setRunners] = useState<Array<{ id: number; name: string }>>([])
  const expEnableRunner = Boolean((import.meta as any).env?.VITE_EXPERIMENTAL_RUNNER)
  const [runnerId, setRunnerId] = useState('')
  const [runnerFilter, setRunnerFilter] = useState('')
  const [showSingleJobRunnerDD, setShowSingleJobRunnerDD] = useState(false)
  const [showBulkJobRunnerDD, setShowBulkJobRunnerDD] = useState(false)
  const [arraySetting, setArraySetting] = useState('')
  const [isGpu, setIsGpu] = useState(false)

  // Bulk job creation states
  const [bulkJobText, setBulkJobText] = useState('')
  const [bulkJobFile, setBulkJobFile] = useState<File | null>(null)
  const [bulkSubmitting, setBulkSubmitting] = useState(false)

  // pickers
  const [showUploads, setShowUploads] = useState(false)
  const [showJobPicker, setShowJobPicker] = useState(false)
  const [uploads, setUploads] = useState<Array<{ name: string; file_size: number; file_create: string; full_path: string }>>([])
  const [uploadsLoading, setUploadsLoading] = useState(false)
  const [uploadsSel, setUploadsSel] = useState<Record<string, boolean>>({})
  const [uploadsFilter, setUploadsFilter] = useState('')

  const protocolSelectionByUserRef = useRef(false)

  // if a clone id is provided in the url (?clone=123), fetch the job and prefill
  useEffect(() => {
    const qp = new URLSearchParams(location.search)
    const cloneId = qp.get('clone')
    if (!cloneId || !/^\d+$/.test(cloneId)) return
    ;(async () => {
      try {
        const res = await apiGet(`/jobs/${cloneId}/`)
        if (!res.ok) return
        const data = await res.json()
        setJobName((data?.job_name ? String(data.job_name) : '') + (data?.job_name ? '-copy' : ''))
        setProtocolId(data?.protocol != null ? String(data.protocol) : '')
        setParameter(data?.parameter ? String(data.parameter) : '')
        setInputFile(data?.input_file ? String(data.input_file) : '')
        setWorkspaceId(data?.workspace != null ? String(data.workspace) : '')
        setComments(data?.comments ? String(data.comments) : '')
        setRunnerId(data?.slave != null ? String(data.slave) : '')
      } catch {}
    })()
  }, [location.search])

  useEffect(() => {
    let aborted = false
    ;(async () => {
      setLoadingOptions(true)
      try {
        const [pRes, wRes] = await Promise.all([
          apiGet('/protocols/?page_size=200'),
          apiGet('/workspaces/?page_size=200'),
        ])
        const pData = await pRes.json()
        const wData = await wRes.json()
        if (!aborted) {
          setProtocols(Array.isArray(pData) ? pData : (pData.results || []))
          setWorkspaces(Array.isArray(wData) ? wData : (wData.results || []))
        }
      } catch {
        if (!aborted) {
          setProtocols([])
          setWorkspaces([])
        }
      } finally {
        if (!aborted) setLoadingOptions(false)
      }
    })()
    return () => { aborted = true }
  }, [])

  // experimental: fetch runners list
  useEffect(() => {
    if (!expEnableRunner) return
    let aborted = false
    ;(async () => {
      try {
        const res = await apiGet('/jobs/runners/')
        const data = await res.json()
        if (!aborted && Array.isArray(data)) setRunners(data)
      } catch {}
    })()
    return () => { aborted = true }
  }, [expEnableRunner])

  async function openUploads() {
    setShowUploads(true)
    setUploadsLoading(true)
    setUploads([])
    setUploadsSel({})
    setUploadsFilter('')
    try {
      const res = await apiGet('/jobs/workspace-files/?type=uploads')
      const data = await res.json()
      if (Array.isArray(data)) setUploads(data)
    } catch {
      setUploads([])
    } finally {
      setUploadsLoading(false)
    }
  }

  

  const canSubmit = useMemo(() => jobName.trim().length > 0 && protocolId.trim().length > 0 && !submitting, [jobName, protocolId, submitting])
  const filteredProtocols = useMemo(() => {
    const q = (protocolFilter || '').trim().toLowerCase()
    if (!q) return protocols
    return protocols.filter(p => p.name.toLowerCase().includes(q) || String(p.id).includes(q))
  }, [protocolFilter, protocols])
  const filteredWorkspaces = useMemo(() => {
    const q = (workspaceFilter || '').trim().toLowerCase()
    if (!q) return workspaces
    return workspaces.filter(w => w.name.toLowerCase().includes(q) || String(w.id).includes(q))
  }, [workspaceFilter, workspaces])
  const filteredRunners = useMemo(() => {
    const q = (runnerFilter || '').trim().toLowerCase()
    if (!q) return runners
    return runners.filter(r => r.name.toLowerCase().includes(q) || String(r.id).includes(q))
  }, [runnerFilter, runners])
  const filteredUploads = useMemo(() => {
    const q = (uploadsFilter || '').trim().toLowerCase()
    if (!q) return uploads
    return uploads.filter(u => u.name.toLowerCase().includes(q))
  }, [uploadsFilter, uploads])
  

  // auto-load default parameter keys when protocol is selected by the user, or when parameters are empty
  useEffect(() => {
    const proto = protocolId.trim()
    if (!proto) return
    const shouldAutofill = protocolSelectionByUserRef.current || parameter.trim().length === 0
    if (!shouldAutofill) { protocolSelectionByUserRef.current = false; return }
    let aborted = false
    ;(async () => {
      try {
        const [stepsRes, refsRes] = await Promise.all([
          apiGet(`/steps/?parent=${encodeURIComponent(proto)}&page_size=1000`),
          apiGet('/references/?page_size=500'),
        ])
        const stepsJson = await stepsRes.json()
        const refsJson = await refsRes.json()
        const stepsArr: Array<any> = Array.isArray(stepsJson) ? stepsJson : (stepsJson.results || [])
        const refsArr: Array<any> = Array.isArray(refsJson) ? refsJson : (refsJson.results || [])
        const pid = parseInt(proto, 10)
        const relSteps = stepsArr.filter(s => Number(s.parent) === pid)
        const predef = new Set<string>([
          'InputFile','LastOutput','Job','ThreadN','Output','LastOutput','Uploaded','Suffix','Workspace','UserBin','JobName',
        ])
        refsArr.forEach(r => { if (r && typeof r.name === 'string') predef.add(r.name) })
        const userKeys: string[] = []
        const seen = new Set<string>()
        const re = /\{\{(.*?)\}\}/gis
        for (const st of relSteps) {
           const par = String(st.parameter || '')
           let m: RegExpExecArray | null
           while ((m = re.exec(par)) !== null) {
            const raw = m[1] || ''
            let name = String(raw.split(':')[0])
            if (name.includes('{{') && !name.includes('}}')) {
              name += '}}'
            }
            if (!name || name.indexOf(';') !== -1) continue
            if (predef.has(name)) continue
            if (seen.has(name)) continue
            seen.add(name)
            userKeys.push(name)
          }
        }
        if (!aborted) {
          const value = userKeys.length ? userKeys.map(k => `${k}=`).join(';') + ';' : ''
          setParameter(value)
        }
      } catch {
        if (!aborted) {
          // leave parameter as-is on failure
        }
      } finally {
        protocolSelectionByUserRef.current = false
      }
    })()
    return () => { aborted = true }
  }, [protocolId])

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit) return
    setSubmitting(true)
    try {
      const payload: any = {
        job_name: jobName.trim(),
        protocol: parseInt(protocolId, 10),
      }
      if (parameter.trim()) payload.parameter = parameter
      if (inputFile.trim()) payload.input_file = inputFile
      if (comments.trim()) payload.comments = comments
      if (workspaceId.trim()) payload.workspace = parseInt(workspaceId, 10)
      else payload.workspace = null
      if (runnerId.trim()) payload.slave = parseInt(runnerId, 10)
      if (arraySetting.trim()) payload.array_setting = arraySetting.trim()
      payload.is_gpu_job = isGpu ? 1 : 0

      const res = await apiPost('/jobs/', JSON.stringify(payload))
      if (res.ok) {
        toast({ title: 'job created', status: 'success', duration: 3000, isClosable: true, position: 'bottom-right' })
        navigate('/jobs')
      } else {
        try {
          const d = await res.json()
          const msg = d?.detail || d?.info || JSON.stringify(d)
          toast({ title: msg, status: 'error', duration: 5000, isClosable: true, position: 'bottom-right' })
        } catch {
          toast({ title: `create failed (${res.status})`, status: 'error', duration: 5000, isClosable: true, position: 'bottom-right' })
        }
      }
    } catch (err: any) {
      toast({ title: err?.message || 'create failed', status: 'error', duration: 5000, isClosable: true, position: 'bottom-right' })
    } finally {
      setSubmitting(false)
    }
  }

  function onReset() {
    setJobName('')
    setProtocolId('')
    setParameter('')
    setInputFile('')
    setWorkspaceId('')
    setComments('')
    setRunnerId('')
    setArraySetting('')
    setIsGpu(false)
  }

  async function onBulkTextSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!bulkJobText.trim() || bulkSubmitting) return
    setBulkSubmitting(true)
    try {
      const payload = new FormData()
      payload.append('job_list', bulkJobText)
      if (runnerId.trim()) payload.append('target', runnerId)

      const res = await fetch('/ui/batch-job-plain/', {
        method: 'POST',
        body: payload,
        headers: {
          'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]')?.getAttribute('value') || '',
        },
      })

      if (res.ok) {
        toast({ title: 'Bulk jobs created successfully', status: 'success', duration: 3000, isClosable: true, position: 'bottom-right' })
        navigate('/jobs')
      } else {
        const errorData = await res.json().catch(() => ({ info: 'Failed to create bulk jobs' }))
        toast({ title: errorData.info || 'Failed to create bulk jobs', status: 'error', duration: 5000, isClosable: true, position: 'bottom-right' })
      }
    } catch (err: any) {
      toast({ title: err?.message || 'Failed to create bulk jobs', status: 'error', duration: 5000, isClosable: true, position: 'bottom-right' })
    } finally {
      setBulkSubmitting(false)
    }
  }

  async function onBulkFileSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!bulkJobFile || bulkSubmitting) return
    setBulkSubmitting(true)
    try {
      const payload = new FormData()
      payload.append('job_list', bulkJobFile)

      const res = await fetch('/ui/batch-job/', {
        method: 'POST',
        body: payload,
        headers: {
          'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]')?.getAttribute('value') || '',
        },
      })

      if (res.ok) {
        toast({ title: 'Bulk jobs created successfully', status: 'success', duration: 3000, isClosable: true, position: 'bottom-right' })
        navigate('/jobs')
      } else {
        const errorData = await res.json().catch(() => ({ info: 'Failed to create bulk jobs' }))
        toast({ title: errorData.info || 'Failed to create bulk jobs', status: 'error', duration: 5000, isClosable: true, position: 'bottom-right' })
      }
    } catch (err: any) {
      toast({ title: err?.message || 'Failed to create bulk jobs', status: 'error', duration: 5000, isClosable: true, position: 'bottom-right' })
    } finally {
      setBulkSubmitting(false)
    }
  }

  

  return (
    <Box mx="auto" px={{ base: 2, md: 4 }}>
      <Flex align="center" justify="space-between" mb={4}>
        <Box>
          <Heading size="lg">Create New Jobs</Heading>
          <Box fontSize="sm" opacity={0.7}>configure protocol, parameters and inputs, then submit to create jobs</Box>
        </Box>
      </Flex>

      <Box borderWidth="1px" borderColor="gray.200" rounded="md" boxShadow="sm" bg="white" w="100%">
        <Tabs variant="enclosed" colorScheme="blue">
          <TabList>
            <Tab><i className="fas fa-tag"></i>&nbsp;Single Job</Tab>
            <Tab><i className="fas fa-tags"></i>&nbsp;Bulk Jobs</Tab>
            <Tab><i className="fas fa-scroll"></i>&nbsp;Bulk Jobs from File</Tab>
          </TabList>

          <TabPanels>
            {/* Single Job Tab */}
            <TabPanel p={{ base: 3, md: 4 }}>
              <Box as="form" onSubmit={onSubmit}>
                <SimpleGrid columns={1} spacing={6}>
                  <Box>
                    <FormControl isRequired>
                      <FormLabel>Job name</FormLabel>
                      <Input value={jobName} onChange={(e)=>setJobName(e.target.value)} placeholder="enter job name" w="100%" />
                      <FormHelperText>give it a descriptive name so it's easy to find later</FormHelperText>
                    </FormControl>

                    <Divider my={4} />

                    <FormControl isRequired>
                      <FormLabel display="flex" alignItems="center" gap={2}>
                        Protocol
                        {protocolId ? (
                          <Tag size="sm" colorScheme="blue">{protocols.find(p=>String(p.id)===protocolId)?.name || protocolId}</Tag>
                        ) : null}
                      </FormLabel>
                      <Menu isOpen={showProtoDD} onClose={()=>setShowProtoDD(false)}>
                        <MenuButton as={Button} onClick={()=>{ setShowProtoDD(!showProtoDD); setShowWsDD(false); setShowSingleJobRunnerDD(false) }} w="100%" textAlign="left" isDisabled={loadingOptions}>
                          Protocol: {protocolId ? (protocols.find(p=>String(p.id)===protocolId)?.name || protocolId) : (loadingOptions ? 'loading…' : 'select')}
                        </MenuButton>
                        <Portal>
                          <MenuList minW="360px" p={2}>
                            <Input size="sm" placeholder="filter protocols" mb={2} value={protocolFilter} onChange={(e)=>setProtocolFilter(e.target.value)} />
                            <Box maxH="260px" overflowY="auto">
                              <MenuOptionGroup type="radio" value={protocolId} onChange={(v)=>{ const val = Array.isArray(v) ? v[0] : v as string; protocolSelectionByUserRef.current = true; setProtocolId(val); setShowProtoDD(false) }}>
                                {filteredProtocols.map(p => (
                                  <MenuItemOption key={p.id} value={String(p.id)}>{p.id} - {p.name}</MenuItemOption>
                                ))}
                              </MenuOptionGroup>
                            </Box>
                          </MenuList>
                        </Portal>
                      </Menu>
                    </FormControl>

                    <Divider my={4} />

                    <FormControl>
                      <FormLabel>Parameters</FormLabel>
                      <Textarea value={parameter} onChange={(e)=>setParameter(e.target.value)} rows={8} placeholder="key=value;key2=value2" w="100%" fontFamily="mono" />
                      <FormHelperText>semicolon-separated; keys and values are passed to the protocol</FormHelperText>
                    </FormControl>

                    <Divider my={4} />

                    <FormControl>
                      <FormLabel>Input files</FormLabel>
                      <Textarea value={inputFile} onChange={(e)=>setInputFile(e.target.value)} rows={8} placeholder="/path/to/file1;/path/to/file2 or {{History:123-output/file.txt}}" w="100%" fontFamily="mono" />
                      <FormHelperText>use semicolons to separate multiple files; you can also insert results from other jobs</FormHelperText>
                      <Flex mt={3} gap={3} wrap="wrap">
                        <Button size="sm" variant="outline" onClick={openUploads}><i className="fa-regular fa-folder-open"></i>&nbsp;Insert from uploads</Button>
                        <Button size="sm" variant="outline" onClick={()=>setShowJobPicker(true)}><i className="fa-regular fa-clone"></i>&nbsp;Insert from job results</Button>
                      </Flex>
                    </FormControl>
                  </Box>

                  <Box>
                    <FormControl>
                      <FormLabel display="flex" alignItems="center" gap={2}>
                        Workspace
                        {workspaceId ? (
                          <Tag size="sm" colorScheme="gray">{workspaces.find(w=>String(w.id)===workspaceId)?.name || workspaceId}</Tag>
                        ) : (
                          <Tag size="sm">none</Tag>
                        )}
                      </FormLabel>
                      <Menu isOpen={showWsDD} onClose={()=>setShowWsDD(false)}>
                        <MenuButton as={Button} onClick={()=>{ setShowWsDD(!showWsDD); setShowProtoDD(false); setShowSingleJobRunnerDD(false) }} w="100%" textAlign="left" isDisabled={loadingOptions}>
                          Workspace: {workspaceId ? (workspaces.find(w=>String(w.id)===workspaceId)?.name || workspaceId) : (loadingOptions ? 'loading…' : '(none)')}
                        </MenuButton>
                        <Portal>
                          <MenuList minW="360px" p={2}>
                            <Input size="sm" placeholder="filter workspaces" mb={2} value={workspaceFilter} onChange={(e)=>setWorkspaceFilter(e.target.value)} />
                            <Box maxH="260px" overflowY="auto">
                              <MenuOptionGroup type="radio" value={workspaceId} onChange={(v)=>{ const val = Array.isArray(v) ? v[0] : v as string; setWorkspaceId(val); setShowWsDD(false) }}>
                                <MenuItemOption value="">(none)</MenuItemOption>
                                {filteredWorkspaces.map(w => (
                                  <MenuItemOption key={w.id} value={String(w.id)}>{w.name}</MenuItemOption>
                                ))}
                              </MenuOptionGroup>
                            </Box>
                          </MenuList>
                        </Portal>
                      </Menu>
                    </FormControl>

                    <Divider my={4} />

                    <FormControl>
                      <FormLabel>Comments</FormLabel>
                      <Textarea value={comments} onChange={(e)=>setComments(e.target.value)} rows={6} placeholder="optional notes" w="100%" />
                    </FormControl>
                  </Box>
                </SimpleGrid>

                {/* Experimental Features Section */}
                <Box mt={6} p={4} borderWidth="1px" borderColor="orange.200" borderRadius="md" bg="orange.50">
                  <Heading size="md" mb={4} color="orange.800">
                    <i className="fas fa-flask"></i> Experimental Features
                  </Heading>
                  <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                    {/* Array Setting */}
                    <FormControl>
                      <FormLabel>Array Setting</FormLabel>
                      <Input
                        value={arraySetting}
                        onChange={(e) => setArraySetting(e.target.value)}
                        placeholder="e.g., 1-10,15,20-25"
                        w="100%"
                      />
                      <FormHelperText>
                        Define array job ranges (e.g., 1-10 for jobs 1 through 10)
                      </FormHelperText>
                    </FormControl>

                    {/* GPU Toggle */}
                    <FormControl>
                      <FormLabel>GPU Required</FormLabel>
                      <Checkbox
                        isChecked={isGpu}
                        onChange={(e) => setIsGpu(e.target.checked)}
                        colorScheme="orange"
                      >
                        Enable GPU support for this job
                      </Checkbox>
                      <FormHelperText>
                        Check if this job requires GPU resources
                      </FormHelperText>
                    </FormControl>

                    {/* Runner Selector */}
                    {expEnableRunner && (
                      <FormControl gridColumn={{ md: "span 2" }}>
                        <FormLabel display="flex" alignItems="center" gap={2}>
                          Runner
                          {runnerId ? (
                            <Tag size="sm" colorScheme="orange">{runners.find(r=>String(r.id)===runnerId)?.name || runnerId}</Tag>
                          ) : (
                            <Tag size="sm">none</Tag>
                          )}
                        </FormLabel>
                        <Menu isOpen={showSingleJobRunnerDD} onClose={()=>setShowSingleJobRunnerDD(false)}>
                          <MenuButton as={Button} onClick={()=>{ setShowSingleJobRunnerDD(!showSingleJobRunnerDD); setShowProtoDD(false); setShowWsDD(false) }} w="100%" textAlign="left">
                            Runner: {runnerId ? (runners.find(r=>String(r.id)===runnerId)?.name || runnerId) : '(none)'}
                          </MenuButton>
                          <Portal>
                            <MenuList minW="360px" p={2}>
                              <Input size="sm" placeholder="filter runners" mb={2} value={runnerFilter} onChange={(e)=>setRunnerFilter(e.target.value)} />
                              <Box maxH="260px" overflowY="auto">
                                <MenuOptionGroup type="radio" value={runnerId} onChange={(v)=>{ const val = Array.isArray(v) ? v[0] : v as string; setRunnerId(val); setShowSingleJobRunnerDD(false) }}>
                                  <MenuItemOption value="">(none)</MenuItemOption>
                                  {filteredRunners.map(r => (
                                    <MenuItemOption key={r.id} value={String(r.id)}>{r.name}</MenuItemOption>
                                  ))}
                                </MenuOptionGroup>
                              </Box>
                            </MenuList>
                          </Portal>
                        </Menu>
                      </FormControl>
                    )}
                  </SimpleGrid>
                </Box>

                <Divider my={5} />

                <Flex align="center" gap={3} justify="flex-end">
                  {loadingOptions && <Flex align="center" gap={2} fontSize="sm" opacity={0.7}><Spinner size="sm" /> loading protocol/workspace options…</Flex>}
                  <Button variant="outline" onClick={onReset} isDisabled={submitting}>Reset</Button>
                  <Button type="submit" colorScheme="blue" isDisabled={!canSubmit} isLoading={submitting}>
                    Create Job
                  </Button>
                </Flex>
              </Box>
            </TabPanel>

            {/* Bulk Jobs Tab */}
            <TabPanel p={{ base: 3, md: 4 }}>
              <Box as="form" onSubmit={onBulkTextSubmit}>
                <FormControl>
                  <FormLabel>Job table</FormLabel>
                  <Textarea
                    value={bulkJobText}
                    onChange={(e)=>setBulkJobText(e.target.value)}
                    rows={12}
                    placeholder="Enter job configurations here..."
                    w="100%"
                    fontFamily="mono"
                  />
                  <FormHelperText>Enter job configurations in tab-separated format</FormHelperText>
                </FormControl>

                <Alert status="info" mt={4} borderRadius="md">
                  <AlertIcon />
                  <Box>
                    <AlertTitle>Format Instructions:</AlertTitle>
                    <AlertDescription>
                      <UnorderedList>
                        <ListItem>Protocol ID</ListItem>
                        <ListItem>Job name</ListItem>
                        <ListItem>Input files</ListItem>
                        <ListItem>Job parameter</ListItem>
                        <ListItem>Repeat (optional)</ListItem>
                        <ListItem>Requires GPU (optional)</ListItem>
                      </UnorderedList>
                      <Box mt={2}>
                        <strong>Example:</strong><br />
                        <Box as="code" fontSize="sm" bg="gray.100" p={2} borderRadius="sm" display="block" whiteSpace="pre">
                          {`1\tMyJob1\t/path/to/file1.txt\tparam1=value1;param2=value2\n2\tMyJob2\t/path/to/file2.txt\tparam1=value3;param2=value4\t1\t1`}
                        </Box>
                      </Box>
                    </AlertDescription>
                  </Box>
                </Alert>

                {/* Runner Selector for Bulk Jobs */}
                {expEnableRunner && (
                  <Box mt={4}>
                    <FormControl>
                      <FormLabel display="flex" alignItems="center" gap={2}>
                        Runner
                        {runnerId ? (
                          <Tag size="sm" colorScheme="orange">{runners.find(r=>String(r.id)===runnerId)?.name || runnerId}</Tag>
                        ) : (
                          <Tag size="sm">none</Tag>
                        )}
                      </FormLabel>
                      <Menu isOpen={showBulkJobRunnerDD} onClose={()=>setShowBulkJobRunnerDD(false)}>
                        <MenuButton as={Button} onClick={()=>{ setShowBulkJobRunnerDD(!showBulkJobRunnerDD); setShowProtoDD(false); setShowWsDD(false) }} w="100%" textAlign="left">
                          Runner: {runnerId ? (runners.find(r=>String(r.id)===runnerId)?.name || runnerId) : '(none)'}
                        </MenuButton>
                        <Portal>
                          <MenuList minW="360px" p={2}>
                            <Input size="sm" placeholder="filter runners" mb={2} value={runnerFilter} onChange={(e)=>setRunnerFilter(e.target.value)} />
                            <Box maxH="260px" overflowY="auto">
                              <MenuOptionGroup type="radio" value={runnerId} onChange={(v)=>{ const val = Array.isArray(v) ? v[0] : v as string; setRunnerId(val); setShowBulkJobRunnerDD(false) }}>
                                <MenuItemOption value="">(none)</MenuItemOption>
                                {filteredRunners.map(r => (
                                  <MenuItemOption key={r.id} value={String(r.id)}>{r.name}</MenuItemOption>
                                ))}
                              </MenuOptionGroup>
                            </Box>
                          </MenuList>
                        </Portal>
                      </Menu>
                    </FormControl>
                  </Box>
                )}

                <Divider my={5} />

                <Flex align="center" gap={3} justify="flex-end">
                  <Button variant="outline" onClick={()=>setBulkJobText('')} isDisabled={bulkSubmitting}>Clear</Button>
                  <Button type="submit" colorScheme="green" isDisabled={!bulkJobText.trim()} isLoading={bulkSubmitting}>
                    Create Bulk Jobs
                  </Button>
                </Flex>
              </Box>
            </TabPanel>

            {/* Bulk Jobs from File Tab */}
            <TabPanel p={{ base: 3, md: 4 }}>
              <Box as="form" onSubmit={onBulkFileSubmit}>
                <FormControl>
                  <FormLabel>Job list file</FormLabel>
                  <Input
                    type="file"
                    accept=".txt,.tsv,.csv"
                    onChange={(e)=>setBulkJobFile(e.target.files?.[0] || null)}
                    w="100%"
                  />
                  <FormHelperText>Upload a file containing job configurations</FormHelperText>
                </FormControl>

                <Alert status="info" mt={4} borderRadius="md">
                  <AlertIcon />
                  <Box>
                    <AlertTitle>File Format Instructions:</AlertTitle>
                    <AlertDescription>
                      <Box mb={2}>The file should contain the following columns separated by tabs:</Box>
                      <UnorderedList>
                        <ListItem>Protocol ID</ListItem>
                        <ListItem>Job name</ListItem>
                        <ListItem>Input files</ListItem>
                        <ListItem>Job parameter</ListItem>
                        <ListItem>Repeat (optional)</ListItem>
                        <ListItem>Requires GPU (optional)</ListItem>
                      </UnorderedList>
                      <Box mt={2}>
                        <strong>Example file content:</strong><br />
                        <Box as="code" fontSize="sm" bg="gray.100" p={2} borderRadius="sm" display="block" whiteSpace="pre">
                          {`1\tMyJob1\t/path/to/file1.txt\tparam1=value1;param2=value2\n2\tMyJob2\t/path/to/file2.txt\tparam1=value3;param2=value4\t1\t1`}
                        </Box>
                      </Box>
                    </AlertDescription>
                  </Box>
                </Alert>

                <Divider my={5} />

                <Flex align="center" gap={3} justify="flex-end">
                  <Button variant="outline" onClick={()=>setBulkJobFile(null)} isDisabled={bulkSubmitting}>Clear</Button>
                  <Button type="submit" colorScheme="green" isDisabled={!bulkJobFile} isLoading={bulkSubmitting}>
                    Upload and Create Jobs
                  </Button>
                </Flex>
              </Box>
            </TabPanel>
          </TabPanels>
        </Tabs>
      </Box>

      {/* uploads picker */}
      <Modal isOpen={showUploads} onClose={()=>setShowUploads(false)} size="4xl" scrollBehavior="inside">
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>Select files from uploads</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            {uploadsLoading ? (
              <Flex align="center" justify="center" p={6}><Spinner size="sm" /> <Box ml={2} fontSize="sm" opacity={0.7}>loading…</Box></Flex>
            ) : (
              <Box>
                <Flex mb={2} gap={2} align="center">
                  <Input size="sm" placeholder="filter files" value={uploadsFilter} onChange={(e)=>setUploadsFilter(e.target.value)} width="100%" />
                </Flex>
                <Table size="sm" variant="striped">
                  <Thead>
                    <Tr>
                      <Th width="60px">Select</Th>
                      <Th>Name</Th>
                      <Th width="100px">Size</Th>
                      <Th width="140px">Created</Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    {filteredUploads.map(u => (
                      <Tr key={u.full_path}>
                        <Td>
                          <Checkbox
                            isChecked={Boolean(uploadsSel[u.full_path])}
                            onChange={(e)=>setUploadsSel(prev=>({ ...prev, [u.full_path]: e.target.checked }))}
                          />
                        </Td>
                        <Td>
                          <Tooltip label={u.name} hasArrow>
                            <Box noOfLines={1} maxW="100%">{u.name}</Box>
                          </Tooltip>
                        </Td>
                        <Td>{formatBytes(Number(u.file_size||0))}</Td>
                        <Td>{u.file_create}</Td>
                      </Tr>
                    ))}
                    {filteredUploads.length === 0 && (
                      <Tr><Td colSpan={4}><Box fontSize="sm" opacity={0.7} textAlign="center" py={4}>No files found</Box></Td></Tr>
                    )}
                  </Tbody>
                </Table>
                <Flex mt={3} justify="flex-end" gap={2}>
                  <Button size="sm" variant="outline" onClick={()=>setShowUploads(false)}>Cancel</Button>
                  <Button size="sm" colorScheme="blue" onClick={()=>{
                    const lines = Object.entries(uploadsSel)
                      .filter(([,v])=>v)
                      .map(([fullPath,]) => {
                        // Extract relative path from full path by removing upload directory prefix
                        // The full path format is typically: /path/to/workspace/user_id/uploads/filename
                        // We want to extract just: filename (excluding the 'uploads' directory)
                        const pathParts = fullPath.split('/')
                        const uploadsIndex = pathParts.findIndex(part => part === 'uploads')
                        if (uploadsIndex !== -1 && uploadsIndex < pathParts.length - 1) {
                          // Take everything after 'uploads' (skip the uploads directory itself)
                          const relativePath = pathParts.slice(uploadsIndex + 1).join('/')
                          return `{{Uploaded:${relativePath}}}`
                        } else {
                          // Fallback: use filename if we can't determine structure
                          const fileName = pathParts[pathParts.length - 1]
                          return `{{Uploaded:${fileName}}}`
                        }
                      })
                    if (lines.length) {
                      setInputFile(prev => (prev ? prev + ";" : "") + lines.join(";"))
                    }
                    setShowUploads(false)
                  }}>Insert</Button>
                </Flex>
              </Box>
            )}
          </ModalBody>
        </ModalContent>
      </Modal>

      <JobResultsPicker
        isOpen={showJobPicker}
        onClose={()=>setShowJobPicker(false)}
        onInsert={(tokens)=>{ if (tokens.length) setInputFile(prev => (prev ? prev+";" : "") + tokens.join(';')) }}
      />
    </Box>
  )
}
