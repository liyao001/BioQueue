import React, { useEffect, useState } from 'react'
import { Box, Button, ButtonGroup, Divider, Flex, FormControl, FormHelperText, FormLabel, Heading, IconButton, Input, SimpleGrid, Table, Tbody, Td, Th, Thead, Tooltip, Tr, Textarea, useToast, Menu, MenuButton, MenuList, MenuItemOption, MenuOptionGroup, Portal } from '@chakra-ui/react'
import { apiGet, apiPost } from '../lib/api'

export default function NewProtocolPage() {
  useEffect(() => { document.title = 'New Protocol – BioQueue' }, [])
  const toast = useToast()

  // Fetch available environments
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
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)

  type StepDraft = { software: string; parameter: string; env?: number | null }
  const [steps, setSteps] = useState<StepDraft[]>([])
  const [newSw, setNewSw] = useState('')
  const [newPar, setNewPar] = useState('')
  const [environments, setEnvironments] = useState<Array<{ id: number; name: string; ve_type: string }>>([])
  const [newEnv, setNewEnv] = useState('')
  const [loadingEnvs, setLoadingEnvs] = useState(false)

  function addStep() {
    const sw = newSw.trim()
    if (!sw) { toast({ title: 'software is required', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' }); return }
    const envId = newEnv ? parseInt(newEnv, 10) : null
    setSteps(prev => [...prev, { software: sw, parameter: newPar, env: envId }])
    setNewSw(''); setNewPar(''); setNewEnv('')
  }
  function removeStep(idx: number) {
    setSteps(prev => prev.filter((_, i) => i !== idx))
  }
  function moveStep(idx: number, dir: 'up'|'down') {
    const j = dir === 'up' ? idx - 1 : idx + 1
    if (j < 0 || j >= steps.length) return
    setSteps(prev => {
      const arr = prev.slice()
      const t = arr[idx]; arr[idx] = arr[j]; arr[j] = t
      return arr
    })
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    const nm = name.trim()
    if (!nm) { toast({ title: 'name is required', status: 'error', duration: 3000, isClosable: true, position: 'bottom-right' }); return }
    setSubmitting(true)
    try {
      const payload: any = { name: nm }
      if (description.trim()) payload.description = description.trim()
      const res = await apiPost('/protocols/', JSON.stringify(payload))
      if (!res.ok) {
        const msg = await (async (r: Response) => { try { const d = await r.json(); return d?.detail || JSON.stringify(d) } catch { return `${r.status}` } })(res)
        toast({ title: msg, status: 'error', duration: 4000, isClosable: true, position: 'bottom-right' })
        return
      }
      const proto = await res.json()
      const protoId = Number(proto?.id)
      if (!isFinite(protoId)) {
        toast({ title: 'protocol created but id missing', status: 'warning', duration: 4000, isClosable: true, position: 'bottom-right' })
        setName(''); setDescription(''); setSteps([])
        return
      }
      // create steps in order
      let ok = 0; let failed = 0
      for (let i = 0; i < steps.length; i++) {
        const st = steps[i]
        try {
          const stepData: any = { parent: protoId, software: st.software, parameter: st.parameter, step_order: i + 1 }
          if (st.env) stepData.env = st.env
          const sres = await apiPost('/steps/', JSON.stringify(stepData))
          if (sres.ok) ok++; else failed++
        } catch {
          failed++
        }
      }
      toast({ title: failed ? `protocol created; steps: ${ok} ok, ${failed} failed` : 'protocol and steps created', status: failed ? 'warning' : 'success', duration: 5000, isClosable: true, position: 'bottom-right' })
      setName(''); setDescription(''); setSteps([]); setNewEnv('')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Box mx="auto" px={{ base: 2, md: 4 }}>
      <Flex align="center" justify="space-between" mb={4}>
        <Box>
          <Heading size="lg">Create New Protocol</Heading>
          <Box fontSize="sm" opacity={0.7}>define protocol metadata and steps, then submit to create it</Box>
        </Box>
      </Flex>

      <Box as="form" onSubmit={onSubmit} borderWidth="1px" borderColor="gray.200" rounded="md" boxShadow="sm" bg="white" p={{ base: 3, md: 4 }} w="100%">
        <SimpleGrid columns={1} spacing={6}>
          <Box>
            <FormControl isRequired>
              <FormLabel>Protocol name</FormLabel>
              <Input value={name} onChange={(e)=>setName(e.target.value)} placeholder="enter protocol name" w="100%" />
              <FormHelperText>give it a descriptive name so it’s easy to find later</FormHelperText>
            </FormControl>

            <Divider my={4} />

            <FormControl>
              <FormLabel>Description</FormLabel>
              <Textarea value={description} onChange={(e)=>setDescription(e.target.value)} rows={4} placeholder="optional notes" w="100%" />
            </FormControl>
          </Box>

          <Box>
            <Heading as="h4" size="sm" mb={2}>Define steps</Heading>
            <Table size="sm" variant="simple">
              <Thead><Tr><Th width="60px">#</Th><Th width="200px">software</Th><Th>parameter</Th><Th width="150px">environment</Th><Th width="140px">actions</Th></Tr></Thead>
              <Tbody>
                {steps.map((st, idx) => (
                  <Tr key={idx}>
                    <Td>{idx + 1}</Td>
                    <Td>
                      <Textarea value={st.software} onChange={(e)=>{
                        const v = e.target.value; setSteps(prev=>prev.map((x,i)=>i===idx?{...x, software:v}:x))
                      }} rows={4} fontFamily="mono" placeholder="shell command or script" />
                    </Td>
                    <Td>
                      <Textarea value={st.parameter} onChange={(e)=>{
                        const v = e.target.value; setSteps(prev=>prev.map((x,i)=>i===idx?{...x, parameter:v}:x))
                      }} rows={6} fontFamily="mono" placeholder="arguments/template; use {{var}} for placeholders" />
                    </Td>
                    <Td>
                      <Menu>
                        <MenuButton as={Button} size="xs" variant="ghost" w="100%" textAlign="left" fontSize="sm">
                          {st.env ? (
                            environments.find(e => e.id === st.env)?.name || `Env ${st.env}`
                          ) : (
                            'none'
                          )}
                        </MenuButton>
                        <Portal>
                          <MenuList minW="250px" p={1}>
                            <MenuOptionGroup
                              type="radio"
                              value={st.env ? String(st.env) : ''}
                              onChange={(v) => {
                                const envId = v ? parseInt(v as string, 10) : null
                                setSteps(prev => prev.map((x, i) => i === idx ? { ...x, env: envId } : x))
                              }}
                            >
                              <MenuItemOption value="">none</MenuItemOption>
                              {environments.map(env => (
                                <MenuItemOption key={env.id} value={String(env.id)} fontSize="sm">
                                  {env.name} ({env.ve_type})
                                </MenuItemOption>
                              ))}
                            </MenuOptionGroup>
                          </MenuList>
                        </Portal>
                      </Menu>
                    </Td>
                    <Td>
                      <ButtonGroup size="xs">
                        <Tooltip label="Move up"><IconButton aria-label="up" onClick={()=>moveStep(idx, 'up')} icon={<i className="fa-solid fa-arrow-up"></i>} /></Tooltip>
                        <Tooltip label="Move down"><IconButton aria-label="down" onClick={()=>moveStep(idx, 'down')} icon={<i className="fa-solid fa-arrow-down"></i>} /></Tooltip>
                        <Tooltip label="Delete"><IconButton aria-label="delete" colorScheme="red" onClick={()=>removeStep(idx)} icon={<i className="fa-regular fa-trash-can"></i>} /></Tooltip>
                      </ButtonGroup>
                    </Td>
                  </Tr>
                ))}
                {steps.length === 0 && (
                  <Tr><Td colSpan={5}><Box fontSize="sm" opacity={0.7}>no steps yet</Box></Td></Tr>
                )}
              </Tbody>
            </Table>

            <Divider my={4} />
            <Heading as="h4" size="sm" mb={2}>Add step</Heading>
            <Flex direction="column" gap={2}>
              <FormControl>
                <FormLabel mb={1}>Software</FormLabel>
                <Textarea value={newSw} onChange={(e)=>setNewSw(e.target.value)} rows={3} fontFamily="mono" placeholder="e.g. fastqc" />
              </FormControl>
              <FormControl>
                <FormLabel mb={1}>Parameter</FormLabel>
                <Textarea value={newPar} onChange={(e)=>setNewPar(e.target.value)} rows={5} fontFamily="mono" placeholder="command-line options or template" />
              </FormControl>
              <FormControl>
                <FormLabel mb={1}>Environment</FormLabel>
                <Menu>
                  <MenuButton as={Button} w="100%" textAlign="left" size="sm" variant="outline">
                    {newEnv ? (
                      environments.find(e => String(e.id) === newEnv)?.name || newEnv
                    ) : (
                      loadingEnvs ? 'Loading environments...' : '(none)'
                    )}
                  </MenuButton>
                  <Portal>
                    <MenuList minW="300px" p={2}>
                      <MenuOptionGroup type="radio" value={newEnv} onChange={(v) => setNewEnv(v as string)}>
                        <MenuItemOption value="">none</MenuItemOption>
                        {environments.map(env => (
                          <MenuItemOption key={env.id} value={String(env.id)}>
                            {env.name} ({env.ve_type})
                          </MenuItemOption>
                        ))}
                      </MenuOptionGroup>
                    </MenuList>
                  </Portal>
                </Menu>
                <FormHelperText>select environment for this step (optional)</FormHelperText>
              </FormControl>
              <Button alignSelf="flex-start" size="sm" variant="outline" onClick={addStep}><i className="fa-solid fa-plus"></i>&nbsp;Add step</Button>
            </Flex>
          </Box>
        </SimpleGrid>

        <Divider my={5} />

        <Flex align="center" gap={3} justify="flex-end">
          <Button type="submit" colorScheme="blue" isLoading={submitting}>
            Create Protocol
          </Button>
        </Flex>
      </Box>
    </Box>
  )
}
