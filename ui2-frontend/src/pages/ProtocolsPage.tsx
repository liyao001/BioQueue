import { useEffect, useState, useMemo } from 'react'
import { useLocation } from 'react-router-dom'
import { Box, Button, ButtonGroup, Divider, Flex, Heading, IconButton, Input, Spinner, Table, Tbody, Td, Th, Thead, Tooltip, Tr, useToast, Tag, Switch, FormControl, FormLabel, FormHelperText, NumberInput, NumberInputField, Modal, ModalOverlay, ModalContent, ModalHeader, ModalCloseButton, ModalBody, ModalFooter, Textarea, Select, Menu, MenuButton, MenuList, MenuItemOption, MenuOptionGroup, Portal } from '@chakra-ui/react'
import { apiGet, apiPost, apiPatch, apiDelete } from '../lib/api'
import Pager from '../components/Pager'

export default function ProtocolsPage() {
  const location = useLocation()
  const toast = useToast()
  useEffect(() => { document.title = 'Protocols – BioQueue' }, [])
  const [loading, setLoading] = useState(false)
  const [protocols, setProtocols] = useState<Array<{ id: number; name: string; description?: string }>>([])
  const [q, setQ] = useState('')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [totalCount, setTotalCount] = useState(0)
  const [sortBy, setSortBy] = useState<'name' | '-id' | 'id'>('-id') // Default: highest ID first

  // steps state
  const [stepsLoading, setStepsLoading] = useState(false)
  const [steps, setSteps] = useState<Array<{ id: number; software: string; parameter: string; step_order: number; env?: number | null }>>([])
  const [editStepId, setEditStepId] = useState<number | null>(null)
  const [editStepSoftware, setEditStepSoftware] = useState('')
  const [editStepParameter, setEditStepParameter] = useState('')
  const [editStepEnv, setEditStepEnv] = useState('')
  const [editEnvFilter, setEditEnvFilter] = useState('')
  const [stepModalOpen, setStepModalOpen] = useState(false)
  const [addingStep, setAddingStep] = useState(false)
  const [newStepSoftware, setNewStepSoftware] = useState('')
  const [newStepParameter, setNewStepParameter] = useState('')
  const [newStepEnv, setNewStepEnv] = useState('')
  const [savingStep, setSavingStep] = useState(false)

  // environments state
  const [environments, setEnvironments] = useState<Array<{ id: number; name: string; ve_type: string }>>([])
  const [loadingEnvs, setLoadingEnvs] = useState(false)
  const [envFilter, setEnvFilter] = useState('')

  // shortcuts state
  const [showShortcuts, setShowShortcuts] = useState(false)
  const [scLoading, setScLoading] = useState(false)
  const [shortcuts, setShortcuts] = useState<Array<{ id: number; label: string; href_template: string; params_template?: string; order: number; active: number }>>([])

  const [newLabel, setNewLabel] = useState('')
  const [newHref, setNewHref] = useState('')
  const [newParams, setNewParams] = useState('')
  const [newOrder, setNewOrder] = useState<string>('0')
  const [newActive, setNewActive] = useState(true)
  const [creating, setCreating] = useState(false)

  const [editingId, setEditingId] = useState<number | null>(null)
  const [editLabel, setEditLabel] = useState('')
  const [editHref, setEditHref] = useState('')
  const [editParams, setEditParams] = useState('')
  const [editOrder, setEditOrder] = useState<string>('0')
  const [savingEdit, setSavingEdit] = useState(false)

  // protocol rename/delete state
  const [renamingProtocol, setRenamingProtocol] = useState<{ id: number; name: string } | null>(null)
  const [editingDescriptionProtocol, setEditingDescriptionProtocol] = useState<{ id: number; description?: string } | null>(null)
  const [newProtocolName, setNewProtocolName] = useState('')
  const [newProtocolDescription, setNewProtocolDescription] = useState('')
  const [savingProtocol, setSavingProtocol] = useState(false)

  // For server-side pagination, we don't need client-side filtering
  // The search is handled by the q parameter in the API call
  const filteredProtocols = protocols

  // Filter environments for the dropdown
  const filteredEnvironments = useMemo(() => {
    const q = (envFilter || '').trim().toLowerCase()
    if (!q) return environments
    return environments.filter(env => env.name.toLowerCase().includes(q) || env.ve_type.toLowerCase().includes(q))
  }, [envFilter, environments])

  // Filter environments for the edit modal
  const filteredEditEnvironments = useMemo(() => {
    const q = (editEnvFilter || '').trim().toLowerCase()
    if (!q) return environments
    return environments.filter(env => env.name.toLowerCase().includes(q) || env.ve_type.toLowerCase().includes(q))
  }, [editEnvFilter, environments])

  async function loadProtocols() {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
        ordering: sortBy
      })
      if (q) params.append('q', q)

      const res = await apiGet(`/protocols/?${params.toString()}`)
      const data = await res.json()
      if (Array.isArray(data)) {
        setProtocols(data)
        setTotalCount(data.length)
      } else {
        setProtocols(data.results || [])
        setTotalCount(parseInt(data.count || 0))
      }
    } catch {
      setProtocols([])
      setTotalCount(0)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadProtocols()
  }, [q, page, pageSize, sortBy])

  // Fetch environments
  useEffect(() => {
    let mounted = true
    ;(async () => {
      setLoadingEnvs(true)
      try {
        const res = await apiGet('/virtual-environments/?page_size=200')
        if (mounted && res.ok) {
          const data = await res.json()
          const envs = Array.isArray(data) ? data : (data.results || [])
          setEnvironments(envs)
        }
      } catch {
        // Silently fail, environments will be empty
      } finally {
        if (mounted) setLoadingEnvs(false)
      }
    })()
    return () => { mounted = false }
  }, [])

  // allow deep-link selection via ?select=ID
  useEffect(() => {
    const sp = new URLSearchParams(location.search)
    const sel = sp.get('select')
    if (sel && /^\d+$/.test(sel)) setSelectedId(parseInt(sel, 10))
  }, [location.search])

  // when a protocol is selected (either by click or via ?select), load its steps
  useEffect(() => {
    if (selectedId != null) {
      loadSteps(selectedId)
    }
  }, [selectedId])

  async function loadSteps(pid: number) {
    setStepsLoading(true)
    try {
      const res = await apiGet(`/steps/?parent=${encodeURIComponent(String(pid))}&page_size=1000`)
      const data = await res.json()
      const rows = Array.isArray(data) ? data : (data.results || [])
      const items = rows.map((r: any) => ({
        id: Number(r.id),
        software: String(r.software || ''),
        parameter: String(r.parameter || ''),
        step_order: Number(r.step_order || 0),
        env: r.env ? Number(r.env) : null
      }))
      items.sort((a: { step_order: number; id: number }, b: { step_order: number; id: number }) => a.step_order - b.step_order || a.id - b.id)
      setSteps(items)
    } catch {
      setSteps([])
    } finally {
      setStepsLoading(false)
    }
  }

  async function loadShortcuts(pid: number) {
    setScLoading(true)
    try {
      const res = await apiGet(`/shortcuts/?protocol=${pid}&page_size=500`)
      const data = await res.json()
      const rows = Array.isArray(data) ? data : (data.results || [])
      setShortcuts(rows.map((r: any) => ({ id: Number(r.id), label: String(r.label || ''), href_template: String(r.href_template || ''), params_template: r.params_template || '', order: Number(r.order || 0), active: Number(r.active || 0) })))
    } catch {
      setShortcuts([])
    } finally {
      setScLoading(false)
    }
  }

  function onSelectProtocol(pid: number) {
    setSelectedId(pid)
    setEditingId(null)
    setEditStepId(null)
    setShowShortcuts(false)
    loadSteps(pid)
  }

  // steps crud
  function onStartEditStep(st: { id: number; software: string; parameter: string; env?: number | null }) {
    setEditStepId(st.id)
    setEditStepSoftware(st.software)
    setEditStepParameter(st.parameter)
    setEditStepEnv(st.env ? String(st.env) : '')
    setStepModalOpen(true)
  }
  function onCancelEditStep() {
    setStepModalOpen(false)
    setEditStepId(null)
    setEditStepSoftware('')
    setEditStepParameter('')
    setEditStepEnv('')
    setEditEnvFilter('')
  }
  async function onSaveEditStep(id: number) {
    setSavingStep(true)
    try {
      const payload: any = { software: editStepSoftware, parameter: editStepParameter }

      // Include environment if selected
      if (editStepEnv && editStepEnv !== '') {
        payload.env = parseInt(editStepEnv, 10)
      } else {
        payload.env = null
      }

      const res = await apiPatch(`/steps/${id}/`, JSON.stringify(payload))
      if (!res.ok) throw new Error(`${res.status}`)
      toast({ title: 'step updated', status: 'success', duration: 2000, isClosable: true, position: 'bottom-right' })
      if (selectedId) loadSteps(selectedId)
      onCancelEditStep()
    } catch (e: any) {
      toast({ title: e?.message || 'update failed', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' })
    } finally {
      setSavingStep(false)
    }
  }
  async function onAddStep() {
    if (!selectedId) return
    const sw = newStepSoftware.trim()
    if (!sw) { toast({ title: 'software is required', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' }); return }
    setAddingStep(true)
    try {
      const nextOrder = (steps.length ? Math.max(...steps.map(s => s.step_order)) + 1 : 1)
      const payload: any = { parent: selectedId, software: sw, parameter: newStepParameter || '', step_order: nextOrder }

      // Include environment if selected
      if (newStepEnv && newStepEnv !== '') {
        payload.env = parseInt(newStepEnv, 10)
      }

      const res = await apiPost('/steps/', JSON.stringify(payload))
      if (!res.ok) throw new Error(`${res.status}`)
      toast({ title: 'step added', status: 'success', duration: 2000, isClosable: true, position: 'bottom-right' })
      setNewStepSoftware(''); setNewStepParameter(''); setNewStepEnv(''); setEnvFilter('')
      loadSteps(selectedId)
    } catch (e: any) {
      toast({ title: e?.message || 'create failed', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' })
    } finally {
      setAddingStep(false)
    }
  }
  async function onDeleteStep(id: number) {
    if (!confirm('Delete this step?')) return
    try {
      const res = await apiDelete(`/steps/${id}/`)
      if (!res.ok) throw new Error(`${res.status}`)
      if (selectedId) loadSteps(selectedId)
    } catch (e: any) {
      toast({ title: e?.message || 'delete failed', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' })
    }
  }
  async function moveStep(id: number, dir: 'up'|'down') {
    const idx = steps.findIndex(s => s.id === id)
    if (idx === -1) return
    const targetIdx = dir === 'up' ? idx - 1 : idx + 1
    if (targetIdx < 0 || targetIdx >= steps.length) return
    const a = steps[idx]
    const b = steps[targetIdx]
    try {
      await apiPatch(`/steps/${a.id}/`, JSON.stringify({ step_order: b.step_order }))
      await apiPatch(`/steps/${b.id}/`, JSON.stringify({ step_order: a.step_order }))
      if (selectedId) loadSteps(selectedId)
    } catch (e: any) {
      toast({ title: e?.message || 'reorder failed', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' })
    }
  }

  // shortcuts crud
  async function onCreateShortcut() {
    if (!selectedId) return
    const label = newLabel.trim()
    const href = newHref.trim()
    if (!label || !href) { toast({ title: 'label and href are required', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' }); return }
    setCreating(true)
    try {
      const payload: any = { protocol: selectedId, label, href_template: href, order: parseInt(newOrder || '0', 10), active: newActive ? 1 : 0 }
      if (newParams.trim()) payload.params_template = newParams.trim()
      const res = await apiPost('/shortcuts/', JSON.stringify(payload))
      if (res.ok) {
        toast({ title: 'shortcut created', status: 'success', duration: 3000, isClosable: true, position: 'bottom-right' })
        setNewLabel(''); setNewHref(''); setNewParams(''); setNewOrder('0'); setNewActive(true)
        loadShortcuts(selectedId)
      } else {
        const msg = await (async (r: Response) => { try { const d = await r.json(); return d?.detail || JSON.stringify(d) } catch { return `${r.status}` } })(res)
        toast({ title: msg, status: 'error', duration: 4000, isClosable: true, position: 'bottom-right' })
      }
    } finally {
      setCreating(false)
    }
  }
  async function onDeleteShortcut(id: number) {
    if (!confirm('Delete this shortcut?')) return
    try {
      const res = await apiDelete(`/shortcuts/${id}/`)
      if (!res.ok) throw new Error(`${res.status}`)
      toast({ title: 'deleted', status: 'success', duration: 2000, isClosable: true, position: 'bottom-right' })
      if (selectedId) loadShortcuts(selectedId)
    } catch (e: any) {
      toast({ title: e?.message || 'delete failed', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' })
    }
  }
  async function onToggleActive(sc: { id: number; active: number }) {
    try {
      const res = await apiPatch(`/shortcuts/${sc.id}/`, JSON.stringify({ active: sc.active ? 0 : 1 }))
      if (!res.ok) throw new Error(`${res.status}`)
      if (selectedId) loadShortcuts(selectedId)
    } catch (e: any) {
      toast({ title: e?.message || 'update failed', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' })
    }
  }
  async function onUpdateOrder(sc: { id: number; order: number }, value: number) {
    try {
      const res = await apiPatch(`/shortcuts/${sc.id}/`, JSON.stringify({ order: value }))
      if (!res.ok) throw new Error(`${res.status}`)
      if (selectedId) loadShortcuts(selectedId)
    } catch (e: any) {
      toast({ title: e?.message || 'update failed', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' })
    }
  }
  function onStartEdit(sc: { id: number; label: string; href_template: string; params_template?: string; order: number }) {
    setEditingId(sc.id)
    setEditLabel(sc.label)
    setEditHref(sc.href_template)
    setEditParams(sc.params_template || '')
    setEditOrder(String(sc.order || 0))
  }
  function onCancelEdit() {
    setEditingId(null)
    setEditLabel('')
    setEditHref('')
    setEditParams('')
    setEditOrder('0')
  }
  async function onSaveEdit(id: number) {
    if (!selectedId) return
    const label = editLabel.trim()
    const href = editHref.trim()
    if (!label || !href) { toast({ title: 'label and href are required', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' }); return }
    setSavingEdit(true)
    try {
      const payload: any = { label, href_template: href, order: parseInt(editOrder || '0', 10) }
      const params = editParams.trim()
      if (params || params === '') payload.params_template = params
      const res = await apiPatch(`/api/shortcuts/${id}/`, JSON.stringify(payload))
      if (!res.ok) throw new Error(`${res.status}`)
      toast({ title: 'shortcut updated', status: 'success', duration: 2000, isClosable: true, position: 'bottom-right' })
      setEditingId(null)
      loadShortcuts(selectedId)
    } catch (e: any) {
      toast({ title: e?.message || 'update failed', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' })
    } finally {
      setSavingEdit(false)
    }
  }

  // protocol rename/delete functions
  function onStartRenameProtocol(protocol: { id: number; name: string }) {
    setRenamingProtocol(protocol)
    setNewProtocolName(protocol.name)
  }

  function onCancelRenameProtocol() {
    setRenamingProtocol(null)
    setNewProtocolName('')
  }

  // protocol description editing functions
  function onStartEditDescriptionProtocol(protocol: { id: number; description?: string }) {
    setEditingDescriptionProtocol(protocol)
    setNewProtocolDescription(protocol.description || '')
  }

  function onCancelEditDescriptionProtocol() {
    setEditingDescriptionProtocol(null)
    setNewProtocolDescription('')
  }

  async function onSaveEditDescriptionProtocol() {
    if (!editingDescriptionProtocol) return
    const newDescription = newProtocolDescription.trim()

    setSavingProtocol(true)
    try {
      const res = await apiPatch(`/protocols/${editingDescriptionProtocol.id}/`, JSON.stringify({ description: newDescription }))
      if (!res.ok) throw new Error(`${res.status}`)
      toast({ title: 'Protocol description updated successfully', status: 'success', duration: 2000, isClosable: true, position: 'bottom-right' })
      loadProtocols()
      onCancelEditDescriptionProtocol()
    } catch (e: any) {
      toast({ title: e?.message || 'Failed to update description', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' })
    } finally {
      setSavingProtocol(false)
    }
  }

  async function onSaveRenameProtocol() {
    if (!renamingProtocol) return
    const newName = newProtocolName.trim()
    if (!newName) {
      toast({ title: 'Protocol name cannot be empty', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' })
      return
    }
    if (newName === renamingProtocol.name) {
      onCancelRenameProtocol()
      return
    }

    setSavingProtocol(true)
    try {
      const res = await apiPatch(`/protocols/${renamingProtocol.id}/`, JSON.stringify({ name: newName }))
      if (!res.ok) throw new Error(`${res.status}`)
      toast({ title: 'Protocol renamed successfully', status: 'success', duration: 2000, isClosable: true, position: 'bottom-right' })
      loadProtocols()
      onCancelRenameProtocol()
    } catch (e: any) {
      toast({ title: e?.message || 'rename failed', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' })
    } finally {
      setSavingProtocol(false)
    }
  }

  async function onDeleteProtocol(protocol: { id: number; name: string }) {
    if (!confirm(`Are you sure you want to delete the protocol "${protocol.name}"? This will also delete all its steps and cannot be undone.`)) return

    try {
      const res = await apiDelete(`/protocols/${protocol.id}/`)
      if (!res.ok) throw new Error(`${res.status}`)
      toast({ title: 'Protocol deleted successfully', status: 'success', duration: 2000, isClosable: true, position: 'bottom-right' })
      loadProtocols()
      if (selectedId === protocol.id) {
        setSelectedId(null)
      }
    } catch (e: any) {
      toast({ title: e?.message || 'delete failed', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' })
    }
  }

  return (
    <Box mx="auto" px={{ base: 2, md: 4 }}>
      <Flex align="center" justify="space-between" mb={4}>
        <Box>
          <Heading size="lg">Protocols</Heading>
          <Box fontSize="sm" opacity={0.7}>manage protocols and their steps; shortcuts are optional helpers</Box>
        </Box>
        <Button as="a" href="/protocols/new" colorScheme="blue" size="sm"><i className="fas fa-plus"></i>&nbsp;New Protocol</Button>
      </Flex>

      <Flex gap={4} wrap="wrap">
        <Box flex="1 1 380px" borderWidth="1px" borderColor="gray.200" rounded="md" bg="white" p={3}>
          <Flex align="center" gap={2} mb={2}>
            <Input placeholder="search protocols" value={q} onChange={(e)=>setQ(e.target.value)} onKeyDown={(e)=>{ if (e.key==='Enter') { setPage(1); loadProtocols() } }} />
            <Button onClick={()=>{ setPage(1); loadProtocols() }} isLoading={loading}>Search</Button>
          </Flex>
          <Flex align="center" gap={2} mb={3}>
            <Box as="label" fontSize="sm">Sort by:</Box>
            <Select size="sm" value={sortBy} onChange={(e) => { setSortBy(e.target.value as any); setPage(1) }} width="160px">
              <option value="-id">ID (descending)</option>
              <option value="id">ID (ascending)</option>
              <option value="name">Name (A-Z)</option>
            </Select>
          </Flex>
          <Box borderWidth="1px" rounded="md" maxH="420px" overflowY="auto">
            <Table size="sm" variant="simple">
              <Thead><Tr><Th width="80px">id</Th><Th>name</Th><Th width="100px">actions</Th></Tr></Thead>
              <Tbody>
                {filteredProtocols.map(p => (
                  <Tr key={p.id} onClick={()=>onSelectProtocol(p.id)} _hover={{ bg: 'gray.50', cursor: 'pointer' }} bg={selectedId===p.id?'cyan.50':undefined}>
                    <Td>{p.id}</Td>
                    <Td>{p.name}</Td>
                    <Td>
                      <ButtonGroup size="xs">
                        <Tooltip label="Select protocol"><IconButton aria-label="select" onClick={(e) => { e.stopPropagation(); onSelectProtocol(p.id) }} icon={<i className="fa-regular fa-hand-pointer"></i>} /></Tooltip>
                      </ButtonGroup>
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </Box>
          <Flex mt={3} align="center" justify="space-between" gap={3}>
            <Flex align="center" gap={2}>
              <Box as="label" fontSize="sm">page size</Box>
              <Select width="auto" size="sm" value={pageSize} onChange={(e)=>{ const v = parseInt(e.target.value)||20; setPageSize(v); setPage(1) }}>
                {[10,20,30,40,50].map(s => <option key={s} value={s}>{s}</option>)}
              </Select>
            </Flex>
            <Pager page={page} totalPages={Math.max(1, Math.ceil((totalCount || 0) / (pageSize || 1)))} loading={loading} onChange={(v)=>setPage(v)} />
          </Flex>
        </Box>

        <Box flex="2 1 720px" borderWidth="1px" borderColor="gray.200" rounded="md" bg="white" p={3}>
          {!selectedId ? (
            <Box fontSize="sm" opacity={0.7}>select a protocol to manage steps</Box>
          ) : (
            <Box>
              <Heading as="h3" size="md">Protocol <Tag ml={2} size="sm" colorScheme="gray">ID {selectedId}</Tag></Heading>
              <Divider my={3} />

              {/* Protocol Editing Section */}
              <Box mb={4} p={3} bg="gray.50" rounded="md">
                <Heading as="h4" size="sm" mb={3}>Edit Protocol</Heading>
                <Flex direction="column" gap={3}>
                  <FormControl>
                    <FormLabel fontSize="sm">Name</FormLabel>
                    <Input
                      size="sm"
                      value={renamingProtocol?.id === selectedId ? newProtocolName : (filteredProtocols.find(p => p.id === selectedId)?.name || '')}
                      onChange={(e) => setNewProtocolName(e.target.value)}
                      isReadOnly={renamingProtocol?.id !== selectedId}
                      bg={renamingProtocol?.id === selectedId ? "white" : "gray.100"}
                    />
                  </FormControl>
                  <FormControl>
                    <FormLabel fontSize="sm">Description</FormLabel>
                    <Textarea
                      size="sm"
                      value={editingDescriptionProtocol?.id === selectedId ? newProtocolDescription : (filteredProtocols.find(p => p.id === selectedId)?.description || '')}
                      onChange={(e) => setNewProtocolDescription(e.target.value)}
                      isReadOnly={editingDescriptionProtocol?.id !== selectedId}
                      bg={editingDescriptionProtocol?.id === selectedId ? "white" : "gray.100"}
                      rows={3}
                      resize="vertical"
                      placeholder="Enter protocol description..."
                    />
                  </FormControl>
                  <Flex gap={2}>
                    {renamingProtocol?.id === selectedId ? (
                      <>
                        <Button size="sm" colorScheme="blue" isLoading={savingProtocol} onClick={onSaveRenameProtocol}>Save Name</Button>
                        <Button size="sm" variant="outline" onClick={onCancelRenameProtocol}>Cancel</Button>
                      </>
                    ) : editingDescriptionProtocol?.id === selectedId ? (
                      <>
                        <Button size="sm" colorScheme="blue" isLoading={savingProtocol} onClick={onSaveEditDescriptionProtocol}>Save Description</Button>
                        <Button size="sm" variant="outline" onClick={onCancelEditDescriptionProtocol}>Cancel</Button>
                      </>
                    ) : (
                      <>
                        <Button size="sm" variant="outline" onClick={() => onStartRenameProtocol(filteredProtocols.find(p => p.id === selectedId)!)}>Edit Name</Button>
                        <Button size="sm" variant="outline" onClick={() => onStartEditDescriptionProtocol(filteredProtocols.find(p => p.id === selectedId)!)}>Edit Description</Button>
                        <Button size="sm" colorScheme="red" variant="outline" onClick={() => onDeleteProtocol(filteredProtocols.find(p => p.id === selectedId)!)}>Delete Protocol</Button>
                      </>
                    )}
                  </Flex>
                </Flex>
              </Box>

              <Heading as="h4" size="sm" mb={2}>Steps</Heading>
              <Divider my={3} />

              {stepsLoading ? (
                <Flex align="center" justify="center" p={6}><Spinner size="sm" /> <Box ml={2} fontSize="sm" opacity={0.7}>loading…</Box></Flex>
              ) : (
                <Table size="sm" variant="simple">
                  <Thead><Tr><Th width="70px">order</Th><Th width="80px">id</Th><Th width="150px">software</Th><Th>parameter</Th><Th width="120px">environment</Th><Th width="140px">actions</Th></Tr></Thead>
                  <Tbody>
                    {steps.map(st => (
                      <Tr key={st.id}>
                        <Td>{st.step_order}</Td>
                        <Td>{st.id}</Td>
                        <Td>
                          <Box as="pre" fontFamily="mono" fontSize="sm" whiteSpace="pre-wrap" wordBreak="break-word" cursor="pointer" title="Click to edit" onClick={()=>onStartEditStep(st)} tabIndex={0} onKeyDown={(e: React.KeyboardEvent)=>{ if (e.key==='Enter' || e.key===' ') onStartEditStep(st) }}>{st.software}</Box>
                        </Td>
                        <Td>
                          <Box as="pre" fontFamily="mono" fontSize="sm" whiteSpace="pre-wrap" wordBreak="break-word" cursor="pointer" title="Click to edit" onClick={()=>onStartEditStep(st)} tabIndex={0} onKeyDown={(e: React.KeyboardEvent)=>{ if (e.key==='Enter' || e.key===' ') onStartEditStep(st) }}>{st.parameter}</Box>
                        </Td>
                        <Td>
                          {st.env ? (
                            environments.find((e: { id: number; name: string; ve_type: string }) => e.id === st.env)?.name || `Env ${st.env}`
                          ) : (
                            <Box fontSize="sm" opacity={0.7}>none</Box>
                          )}
                        </Td>
                        <Td>
                          <ButtonGroup size="xs">
                            <Tooltip label="Edit code"><IconButton aria-label="edit" onClick={()=>onStartEditStep(st)} icon={<i className="fa-regular fa-pen-to-square"></i>} /></Tooltip>
                            <Tooltip label="Move up"><IconButton aria-label="up" onClick={()=>moveStep(st.id, 'up')} icon={<i className="fa-solid fa-arrow-up"></i>} /></Tooltip>
                            <Tooltip label="Move down"><IconButton aria-label="down" onClick={()=>moveStep(st.id, 'down')} icon={<i className="fa-solid fa-arrow-down"></i>} /></Tooltip>
                            <Tooltip label="Delete"><IconButton aria-label="delete" colorScheme="red" onClick={()=>onDeleteStep(st.id)} icon={<i className="fa-regular fa-trash-can"></i>} /></Tooltip>
                          </ButtonGroup>
                        </Td>
                      </Tr>
                    ))}
                    {steps.length === 0 && (
                      <Tr><Td colSpan={6}><Box fontSize="sm" opacity={0.7}>no steps</Box></Td></Tr>
                    )}
                  </Tbody>
                </Table>
              )}

              <Divider my={4} />
              <Heading as="h4" size="sm" mb={2}>Add step</Heading>
              <Flex direction="column" gap={2}>
                <FormControl>
                  <FormLabel mb={1}>Software</FormLabel>
                  <Textarea value={newStepSoftware} onChange={(e)=>setNewStepSoftware(e.target.value)} rows={3} placeholder="e.g. fastqc" fontFamily="mono" />
                </FormControl>
                <FormControl>
                  <FormLabel mb={1}>Parameter</FormLabel>
                  <Textarea value={newStepParameter} onChange={(e)=>setNewStepParameter(e.target.value)} rows={6} placeholder="command-line options or template" fontFamily="mono" />
                </FormControl>
                <FormControl>
                  <FormLabel mb={1}>Environment</FormLabel>
                  <Menu onClose={() => setEnvFilter('')}>
                    <MenuButton as={Button} w="100%" textAlign="left" size="sm" variant="outline">
                      {newStepEnv ? (
                        environments.find((e: { id: number; name: string; ve_type: string }) => String(e.id) === newStepEnv)?.name || newStepEnv
                      ) : (
                        loadingEnvs ? 'Loading environments...' : '(none)'
                      )}
                    </MenuButton>
                    <Portal>
                      <MenuList minW="360px" p={2} zIndex={1600}>
                        <Input size="sm" placeholder="filter environments" mb={2} value={envFilter} onChange={(e)=>setEnvFilter(e.target.value)} />
                        <Box maxH="260px" overflowY="auto">
                          <MenuOptionGroup type="radio" value={newStepEnv} onChange={(v) => { setNewStepEnv(v as string); }}>
                            <MenuItemOption value="">none</MenuItemOption>
                            {filteredEnvironments.map((env: { id: number; name: string; ve_type: string }) => (
                              <MenuItemOption key={env.id} value={String(env.id)} fontSize="sm">
                                {env.name} ({env.ve_type})
                              </MenuItemOption>
                            ))}
                            {/* Show selected environment even if filtered out */}
                            {newStepEnv && !filteredEnvironments.find((e: { id: number; name: string; ve_type: string }) => String(e.id) === newStepEnv) && (
                              <MenuItemOption value={newStepEnv} fontSize="sm" opacity={0.6}>
                                {environments.find((e: { id: number; name: string; ve_type: string }) => String(e.id) === newStepEnv)?.name || newStepEnv} (selected)
                              </MenuItemOption>
                            )}
                          </MenuOptionGroup>
                          {filteredEnvironments.length === 0 && !newStepEnv && envFilter && (
                            <Box fontSize="sm" opacity={0.7} textAlign="center" py={2}>
                              no environments match "{envFilter}"
                            </Box>
                          )}
                        </Box>
                      </MenuList>
                    </Portal>
                  </Menu>
                  <FormHelperText>select environment for this step (optional)</FormHelperText>
                </FormControl>
                <Button alignSelf="flex-start" size="sm" colorScheme="blue" isLoading={addingStep} onClick={onAddStep}>Add</Button>
              </Flex>

              <Divider my={4} />
              <Flex align="center" justify="space-between">
                <Heading as="h3" size="sm">Shortcuts</Heading>
                <Button size="sm" variant="outline" onClick={() => { setShowShortcuts(!showShortcuts); if (!showShortcuts && selectedId) loadShortcuts(selectedId) }}>
                  {showShortcuts ? 'Hide' : 'Manage'}
                </Button>
              </Flex>

              {showShortcuts && (
                <Box mt={3}>
                  {scLoading ? (
                    <Flex align="center" justify="center" p={6}><Spinner size="sm" /> <Box ml={2} fontSize="sm" opacity={0.7}>loading…</Box></Flex>
                  ) : (
                    <Table size="sm" variant="simple">
                      <Thead><Tr><Th>label</Th><Th>href</Th><Th>params</Th><Th width="100px">order</Th><Th width="100px">active</Th><Th width="160px">actions</Th></Tr></Thead>
                      <Tbody>
                        {shortcuts.map(sc => (
                          <Tr key={sc.id}>
                            <Td>{editingId===sc.id ? (<Input size="sm" value={editLabel} onChange={(e)=>setEditLabel(e.target.value)} />) : sc.label}</Td>
                            <Td>{editingId===sc.id ? (<Input size="sm" value={editHref} onChange={(e)=>setEditHref(e.target.value)} />) : sc.href_template}</Td>
                            <Td>{editingId===sc.id ? (<Input size="sm" value={editParams} onChange={(e)=>setEditParams(e.target.value)} />) : (sc.params_template || '')}</Td>
                            <Td>
                              {editingId===sc.id ? (
                                <NumberInput size="sm" width="90px" value={editOrder} onChange={(v)=>setEditOrder(v)}>
                                  <NumberInputField />
                                </NumberInput>
                              ) : (
                                <NumberInput size="sm" width="90px" value={String(sc.order)} onChange={(v)=>{ const n = parseInt(v || '0', 10); if (!isNaN(n)) onUpdateOrder(sc, n) }}>
                                  <NumberInputField />
                                </NumberInput>
                              )}
                            </Td>
                            <Td>
                              <Switch size="sm" isChecked={!!sc.active} onChange={()=>onToggleActive(sc)} />
                            </Td>
                            <Td>
                              <ButtonGroup size="xs">
                                {editingId===sc.id ? (
                                  <>
                                    <Button colorScheme="blue" isLoading={savingEdit} onClick={()=>onSaveEdit(sc.id)}>Save</Button>
                                    <Button variant="outline" onClick={onCancelEdit}>Cancel</Button>
                                  </>
                                ) : (
                                  <>
                                    <Tooltip label="Edit"><IconButton aria-label="edit" onClick={()=>onStartEdit(sc)} icon={<i className="fa-regular fa-pen-to-square"></i>} /></Tooltip>
                                    <Tooltip label="Delete"><IconButton aria-label="delete" colorScheme="red" onClick={()=>onDeleteShortcut(sc.id)} icon={<i className="fa-regular fa-trash-can"></i>} /></Tooltip>
                                  </>
                                )}
                              </ButtonGroup>
                            </Td>
                          </Tr>
                        ))}
                        {shortcuts.length === 0 && (
                          <Tr><Td colSpan={6}><Box fontSize="sm" opacity={0.7}>no shortcuts</Box></Td></Tr>
                        )}
                      </Tbody>
                    </Table>
                  )}

                  <Divider my={4} />
                  <Heading as="h4" size="sm" mb={2}>Add shortcut</Heading>
                  <Flex direction="column" gap={2}>
                    <FormControl>
                      <FormLabel mb={1}>Label</FormLabel>
                      <Input value={newLabel} onChange={(e)=>setNewLabel(e.target.value)} placeholder="e.g. Evaluate" />
                    </FormControl>
                    <FormControl>
                      <FormLabel mb={1}>Href template</FormLabel>
                      <Input value={newHref} onChange={(e)=>setNewHref(e.target.value)} placeholder="e.g. /ui/dec-eval-runs/{id}" />
                    </FormControl>
                    <FormControl>
                      <FormLabel mb={1}>Params template (optional)</FormLabel>
                      <Input value={newParams} onChange={(e)=>setNewParams(e.target.value)} placeholder="e.g. ?foo=bar" />
                    </FormControl>
                    <Flex gap={4} align="center" wrap="wrap">
                      <FormControl width="140px">
                        <FormLabel mb={1}>Order</FormLabel>
                        <NumberInput size="sm" value={newOrder} onChange={(v)=>setNewOrder(v)}>
                          <NumberInputField />
                        </NumberInput>
                      </FormControl>
                      <FormControl display="flex" alignItems="center" width="200px">
                        <FormLabel mb={0} mr={3}>Active</FormLabel>
                        <Switch isChecked={newActive} onChange={(e)=>setNewActive(e.target.checked)} />
                      </FormControl>
                      <Button onClick={onCreateShortcut} isLoading={creating} colorScheme="blue">Create</Button>
                    </Flex>
                  </Flex>
                </Box>
              )}
            </Box>
          )}
        </Box>
      </Flex>

      {/* step code editor modal */}
      <Modal isOpen={stepModalOpen} onClose={onCancelEditStep} size="5xl" scrollBehavior="inside">
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>Edit step code</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <Flex gap={4} direction="column">
              <FormControl>
                <FormLabel>Software</FormLabel>
                <Textarea value={editStepSoftware} onChange={(e)=>setEditStepSoftware(e.target.value)} rows={6} fontFamily="mono" placeholder="shell command or script" />
              </FormControl>
              <FormControl>
                <FormLabel>Parameter</FormLabel>
                <Textarea value={editStepParameter} onChange={(e)=>setEditStepParameter(e.target.value)} rows={12} fontFamily="mono" placeholder="arguments/template; use {{var}} for placeholders" />
              </FormControl>
              <FormControl>
                <FormLabel>Environment</FormLabel>
                <Menu onClose={() => setEditEnvFilter('')}>
                  <MenuButton as={Button} w="100%" textAlign="left" size="sm" variant="outline">
                    {editStepEnv ? (
                      environments.find((e: { id: number; name: string; ve_type: string }) => String(e.id) === editStepEnv)?.name || editStepEnv
                    ) : (
                      loadingEnvs ? 'Loading environments...' : '(none)'
                    )}
                  </MenuButton>
                  <Portal>
                    <MenuList minW="360px" p={2} zIndex={1600}>
                      <Input size="sm" placeholder="filter environments" mb={2} value={editEnvFilter} onChange={(e)=>setEditEnvFilter(e.target.value)} />
                      <Box maxH="260px" overflowY="auto">
                        <MenuOptionGroup type="radio" value={editStepEnv} onChange={(v) => { setEditStepEnv(v as string); }}>
                          <MenuItemOption value="">none</MenuItemOption>
                          {filteredEditEnvironments.map((env: { id: number; name: string; ve_type: string }) => (
                            <MenuItemOption key={env.id} value={String(env.id)} fontSize="sm">
                              {env.name} ({env.ve_type})
                            </MenuItemOption>
                          ))}
                          {/* Show selected environment even if filtered out */}
                          {editStepEnv && !filteredEditEnvironments.find((e: { id: number; name: string; ve_type: string }) => String(e.id) === editStepEnv) && (
                            <MenuItemOption value={editStepEnv} fontSize="sm" opacity={0.6}>
                              {environments.find((e: { id: number; name: string; ve_type: string }) => String(e.id) === editStepEnv)?.name || editStepEnv} (selected)
                            </MenuItemOption>
                          )}
                        </MenuOptionGroup>
                        {filteredEditEnvironments.length === 0 && !editStepEnv && editEnvFilter && (
                          <Box fontSize="sm" opacity={0.7} textAlign="center" py={2}>
                            no environments match "{editEnvFilter}"
                          </Box>
                        )}
                      </Box>
                    </MenuList>
                  </Portal>
                </Menu>
                <FormHelperText>select environment for this step (optional)</FormHelperText>
              </FormControl>
            </Flex>
          </ModalBody>
          <ModalFooter>
            <Button variant="outline" mr={3} onClick={onCancelEditStep}>Cancel</Button>
            <Button colorScheme="blue" isLoading={savingStep} onClick={()=>{ if (editStepId!=null) onSaveEditStep(editStepId) }}>Save</Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </Box>
  )
}
