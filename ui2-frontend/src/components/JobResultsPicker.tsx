import { useEffect, useRef, useState } from 'react'
import { Box, Button, Flex, Heading, Input, Modal, ModalBody, ModalCloseButton, ModalContent, ModalHeader, ModalOverlay, Spinner, Table, Thead, Tbody, Tr, Th, Td, Tooltip } from '@chakra-ui/react'
import { apiGet } from '../lib/api'
import { formatBytes } from '../lib/format'
import Pager from './Pager'

type JobRow = { id: number; job_name: string }
type JobFileRow = { name: string; trace: string; file_size?: number }

export default function JobResultsPicker({
  isOpen,
  onClose,
  onInsert,
  initialQuery,
  pageSize = 50,
}: {
  isOpen: boolean
  onClose: () => void
  onInsert: (tokens: string[]) => void
  initialQuery?: string
  pageSize?: number
}) {
  const [jobSearch, setJobSearch] = useState(initialQuery || '')
  const [jobSearchLoading, setJobSearchLoading] = useState(false)
  const [jobResults, setJobResults] = useState<JobRow[]>([])
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null)
  const [jobFiles, setJobFiles] = useState<JobFileRow[]>([])
  const [jobFilesLoading, setJobFilesLoading] = useState(false)
  const [jobFilesSel, setJobFilesSel] = useState<Record<string, boolean>>({})
  const [jobFilesFilter, setJobFilesFilter] = useState('')
  const [jobFilesPage, setJobFilesPage] = useState(1)
  const [jobFilesTotal, setJobFilesTotal] = useState(0)
  const [jobOwnerId, setJobOwnerId] = useState<number | null>(null)
  const [jobFilesShared, setJobFilesShared] = useState<boolean>(false)
  const [jobFilesPageSize] = useState(pageSize)
  const [jobsPage, setJobsPage] = useState(1)
  const [jobsTotalPages, setJobsTotalPages] = useState(0)
  const [jobsPageSize] = useState(7) // Page size for jobs search
  const jobSearchTimerRef = useRef<number | null>(null)
  const jobFilesFilterTimerRef = useRef<number | null>(null)

  useEffect(() => {
    if (!isOpen) return
    setJobSearch(initialQuery || '')
  }, [isOpen, initialQuery])

  function resetAll() {
    setJobSearch('')
    setJobResults([])
    setSelectedJobId(null)
    setJobFiles([])
    setJobFilesSel({})
    setJobFilesFilter('')
    setJobSearchLoading(false)
    setJobFilesLoading(false)
    setJobFilesPage(1)
    setJobFilesTotal(0)
    setJobOwnerId(null)
    setJobFilesShared(false)
    setJobsPage(1)
    setJobsTotalPages(0)
    if (jobSearchTimerRef.current) {
      window.clearTimeout(jobSearchTimerRef.current)
      jobSearchTimerRef.current = null
    }
    if (jobFilesFilterTimerRef.current) {
      window.clearTimeout(jobFilesFilterTimerRef.current)
      jobFilesFilterTimerRef.current = null
    }
  }

  async function onSearchJobs(page: number = jobsPage) {
    const q = (jobSearch || '').trim()
    if (!q) {
      setJobResults([])
      setJobsTotalPages(0)
      return
    }
    setJobSearchLoading(true)
    await new Promise(r=>setTimeout(r,0))
    try {
      const params = new URLSearchParams()
      if (/^\d+$/.test(q)) params.set('id', q)
      else params.set('job_name', q)
      params.set('page_size', String(jobsPageSize))
      params.set('page', String(page))

      const [ownRes, sharedRes] = await Promise.all([
        apiGet(`/jobs/search/?${params.toString()}`),
        apiGet(`/jobs/shared-search/?q=${encodeURIComponent(q)}`),
      ])
      const ownData = await ownRes.json()
      const sharedData = await sharedRes.json()

      const ownRows = Array.isArray(ownData) ? ownData : (ownData.results || [])
      const sharedRows = Array.isArray(sharedData) ? sharedData : []

      // Calculate total pages from the own jobs response (assuming it has pagination info)
      let totalPages = 0
      if (!Array.isArray(ownData) && ownData.count) {
        totalPages = Math.ceil(ownData.count / jobsPageSize)
      } else {
        // Fallback: if no count, assume 1 page
        totalPages = ownRows.length > 0 ? 1 : 0
      }

      const merged: JobRow[] = []
      ownRows.forEach((r: any) => merged.push({ id: Number(r.id), job_name: String(r.job_name || '') }))
      sharedRows.forEach((r: any) => merged.push({ id: Number(r.id), job_name: String(r.job_name || '') }))

      setJobResults(merged)
      setJobsTotalPages(totalPages)
      setJobsPage(page)
    } catch {
      setJobResults([])
      setJobsTotalPages(0)
    } finally {
      setJobSearchLoading(false)
    }
  }

  useEffect(() => {
    if (jobSearchTimerRef.current) {
      window.clearTimeout(jobSearchTimerRef.current)
      jobSearchTimerRef.current = null
    }
    const q = (jobSearch || '').trim()
    if (q.length >= 3) {
      jobSearchTimerRef.current = window.setTimeout(() => { onSearchJobs(1) }, 350)
    } else {
      setJobResults([])
      setJobsTotalPages(0)
      setJobsPage(1)
      setSelectedJobId(null)
      setJobFiles([])
      setJobFilesSel({})
    }
    return () => {
      if (jobSearchTimerRef.current) {
        window.clearTimeout(jobSearchTimerRef.current)
        jobSearchTimerRef.current = null
      }
    }
  }, [jobSearch])

  function handleJobsPageChange(newPage: number) {
    setJobsPage(newPage)
    onSearchJobs(newPage)
  }

  async function loadJobFiles(jobId: number) {
    setSelectedJobId(jobId)
    setJobFiles([])
    setJobFilesSel({})
    setJobFilesFilter('')
    setJobFilesTotal(0)
    setJobFilesPage(1)
    try {
      const jres = await apiGet(`/jobs/${jobId}/?scope=all`)
      if (jres.ok) {
        const jdata = await jres.json()
        if (jdata && typeof jdata.user_id !== 'undefined') setJobOwnerId(Number(jdata.user_id))
        else setJobOwnerId(null)
      } else {
        setJobOwnerId(null)
      }
    } catch { setJobOwnerId(null) }
    await fetchJobFiles(jobId, 1)
  }

  async function fetchJobFiles(jobId: number, page: number) {
    setJobFilesLoading(true)
    await new Promise(r=>setTimeout(r,0))
    try {
      const offset = (Math.max(1, page) - 1) * jobFilesPageSize
      const limit = jobFilesPageSize
      const q = encodeURIComponent((jobFilesFilter || '').trim())
      const qParam = q ? `&q=${q}` : ''
      let res = await apiGet(`/jobs/${jobId}/files/?limit=${limit}&offset=${offset}&sort=name&order=asc${qParam}`)
      let usedShared = false
      if (res.status === 403 || res.status === 404) {
        res = await apiGet(`/jobs/shared-files/?job_id=${jobId}&limit=${limit}&offset=${offset}&sort=name&order=asc${qParam}`)
        usedShared = true
      }
      const data = await res.json()
      const items = Array.isArray(data) ? data : (data.items || [])
      const total = Array.isArray(data) ? items.length : Number(data.total || items.length)
      setJobFiles(items.map((x: any) => ({ name: String(x.name || ''), trace: String(x.trace || ''), file_size: Number(x.file_size || 0) })))
      setJobFilesTotal(total)
      setJobFilesPage(page)
      setJobFilesShared(usedShared)
    } catch {
      setJobFiles([])
      setJobFilesTotal(0)
      setJobFilesShared(false)
    } finally {
      setJobFilesLoading(false)
    }
  }


  useEffect(() => {
    // Debounce like job search: trigger when cleared or >= 3 chars
    if (jobFilesFilterTimerRef.current) {
      window.clearTimeout(jobFilesFilterTimerRef.current)
      jobFilesFilterTimerRef.current = null
    }
    if (!selectedJobId) return
    const q = (jobFilesFilter || '').trim()
    if (q.length === 0 || q.length >= 3) {
      jobFilesFilterTimerRef.current = window.setTimeout(() => {
        setJobFilesPage(1)
        fetchJobFiles(selectedJobId, 1)
      }, 350)
    }
    return () => {
      if (jobFilesFilterTimerRef.current) {
        window.clearTimeout(jobFilesFilterTimerRef.current)
        jobFilesFilterTimerRef.current = null
      }
    }
  }, [jobFilesFilter, selectedJobId])

  function handleClose() {
    resetAll()
    onClose()
  }

  function doInsert() {
    if (!selectedJobId) return
    const tokens = Object.entries(jobFilesSel).filter(([, v]) => v).map(([name]) => {
      if (jobFilesShared) {
        const owner = jobOwnerId != null ? jobOwnerId : 'User'
        return `{{CrossAccess:${owner}-${selectedJobId}-${name}}}`
      }
      return `{{History:${selectedJobId}-${name}}}`
    })
    if (tokens.length) onInsert(tokens)
    handleClose()
  }

  return (
    <Modal isOpen={isOpen} onClose={handleClose} size="6xl" scrollBehavior="inside" motionPreset="none">
      <ModalOverlay />
      <ModalContent>
        <ModalHeader>Select results from a job</ModalHeader>
        <ModalCloseButton />
        <ModalBody>
          <Flex align="center" gap={2} wrap="wrap">
            <Input
              placeholder="type ≥ 3 chars to search jobs (id or name)"
              value={jobSearch}
              onChange={(e)=>setJobSearch(e.target.value)}
              onKeyDown={(e)=>{ if (e.key === 'Enter') { e.preventDefault(); onSearchJobs(1) } }}
              autoFocus
              flex="1"
            />
            <Button size="sm" type="button" onClick={() => onSearchJobs(1)} isLoading={jobSearchLoading}>Search</Button>
          </Flex>

          <Box mt={3} borderWidth="1px" rounded="md" p={2}>
            <Heading as="h4" size="sm" mb={2}>Jobs</Heading>
            <Box maxH="260px" overflowY="auto" position="relative">
              <Table size="sm" variant="simple">
                <Thead position="sticky" top={0} bg="white" zIndex={1}>
                  <Tr><Th width="80px">id</Th><Th>name</Th></Tr>
                </Thead>
                <Tbody>
                  {jobResults.map(j => (
                    <Tr key={j.id} onClick={()=>loadJobFiles(j.id)} _hover={{ bg: 'gray.50', cursor: 'pointer' }} bg={selectedJobId === j.id ? 'cyan.50' : undefined}>
                      <Td>{j.id}</Td>
                      <Td>
                        <Tooltip label={j.job_name} hasArrow>
                          <Box noOfLines={1}>{j.job_name}</Box>
                        </Tooltip>
                      </Td>
                    </Tr>
                  ))}
                  {!jobSearchLoading && jobResults.length === 0 && (
                    <Tr><Td colSpan={2}><Box fontSize="sm" opacity={0.7}>no results</Box></Td></Tr>
                  )}
                </Tbody>
              </Table>
            </Box>
            {jobsTotalPages > 1 && (
              <Pager
                page={jobsPage}
                totalPages={jobsTotalPages}
                loading={jobSearchLoading}
                onChange={handleJobsPageChange}
              />
            )}
          </Box>

          <Box mt={4} borderWidth="1px" rounded="md" p={2}>
            <Heading as="h4" size="sm" mb={2}>Files {selectedJobId ? `(job #${selectedJobId})` : ''}</Heading>
            {jobFilesLoading ? (
              <Flex align="center" justify="center" p={6}><Spinner size="sm" /> <Box ml={2} fontSize="sm" opacity={0.7}>loading…</Box></Flex>
            ) : (
              <Box maxH="340px" overflowY="auto" position="relative">
                <Box position="sticky" top={0} bg="white" zIndex={1} pb={2} pt={1}>
                  <Flex gap={2} align="center">
                    <Input placeholder="filter files (≥ 3 chars)" value={jobFilesFilter} onChange={(e)=>setJobFilesFilter(e.target.value)} flex="1" />
                    <Button size="sm" type="button" onClick={()=>{ if (selectedJobId) { setJobFilesPage(1); fetchJobFiles(selectedJobId, 1) } }}>Filter</Button>
                  </Flex>
                </Box>
                <Table size="sm" variant="simple">
                  <Thead><Tr><Th width="100px">Select</Th><Th>Name</Th><Th width="120px">Size</Th></Tr></Thead>
                  <Tbody>
                    {jobFiles.map(f => (
                      <Tr key={f.trace}>
                        <Td><input type="checkbox" checked={Boolean(jobFilesSel[f.name])} onChange={(e)=>setJobFilesSel(prev=>({ ...prev, [f.name]: e.target.checked }))} /></Td>
                        <Td>
                          <Tooltip label={f.name} hasArrow>
                            <Box noOfLines={1} maxW="100%">{f.name}</Box>
                          </Tooltip>
                        </Td>
                        <Td>{formatBytes(Number(f.file_size||0))}</Td>
                      </Tr>
                    ))}
                    {selectedJobId && !jobFilesLoading && jobFiles.length === 0 && (
                      <Tr><Td colSpan={3}><Box fontSize="sm" opacity={0.7}>no files</Box></Td></Tr>
                    )}
                  </Tbody>
                </Table>
              </Box>
            )}
            <Pager
              page={jobFilesPage}
              totalPages={Math.max(1, Math.ceil(((jobFilesTotal || 0)) / (jobFilesPageSize || 1)))}
              loading={jobFilesLoading}
              onChange={(v)=>{ if (selectedJobId) fetchJobFiles(selectedJobId, v) }}
            />
          </Box>
          <Flex mt={3} justify="flex-end" gap={2}>
            <Button size="sm" variant="outline" onClick={handleClose}>Cancel</Button>
            <Button size="sm" colorScheme="blue" isDisabled={!selectedJobId} onClick={doInsert}>Insert</Button>
          </Flex>
        </ModalBody>
      </ModalContent>
    </Modal>
  )
}


