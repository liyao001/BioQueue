import { Box, Button, ChakraProvider, Flex, Image, Menu, MenuButton, MenuList, MenuItem, Spacer, Badge, Text, Link as ChakraLink } from '@chakra-ui/react'
import { createRoot, type Root } from 'react-dom/client'
import { BrowserRouter, Routes, Route, Link, useLocation, Navigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { apiGet, apiPost } from './lib/api'
import './index.css'
import JobMonitorPage from './pages/JobMonitorPage'
import CreateJobPage from './pages/CreateJobPage'
import LoginPage from './pages/LoginPage'
import ProtocolsPage from './pages/ProtocolsPage'
import NewProtocolPage from './pages/NewProtocolPage'
import ReferencesPage from './pages/ReferencesPage'
import VirtualEnvsPage from './pages/VirtualEnvsPage'

function Shell() {
  const loc = useLocation()
  const [me, setMe] = useState<{ username?: string; is_staff?: boolean } | null>(null)
  const [runningJobsCount, setRunningJobsCount] = useState<number>(0)
  const [loggingOut, setLoggingOut] = useState(false)
  const [authChecked, setAuthChecked] = useState(false)

  const checkAuth = async () => {
    try {
      const res = await apiGet('/auth/me/')
      if (res.ok) {
        const data = await res.json()
        // Only set user data if we got a valid response with a username
        if (data && data.username) {
          setMe(data)
        } else {
          setMe(null)
        }
      } else {
        setMe(null)
      }
    } catch (error) {
      console.log('Auth check failed:', error)
      setMe(null)
    } finally {
      setAuthChecked(true)
    }
  }

  const handleLogout = async () => {
    setLoggingOut(true)
    try {
      await apiPost('/auth/logout/')
      await checkAuth() // Re-check auth status after logout
    } catch (error) {
      console.error('Logout failed:', error)
      setMe(null) // Fallback to null if logout fails
    } finally {
      setLoggingOut(false)
    }
  }

  useEffect(() => {
    checkAuth()
  }, [])

  useEffect(() => {
    let mounted = true
    const fetchRunningJobsCount = async () => {
      try {
        const res = await apiGet('/jobs/status-counts/')
        if (res.ok) {
          const data = await res.json()
          // Find running jobs count (status value 1) from the counts array
          const runningCount = data.counts?.find((item: any) => item.value === 1)?.count || 0
          if (mounted) setRunningJobsCount(runningCount)
        }
      } catch {
        // Silently fail, badge will show 0
      }
    }

    fetchRunningJobsCount()
    // Refresh every 30 seconds
    const interval = setInterval(fetchRunningJobsCount, 30000)
    return () => {
      mounted = false
      clearInterval(interval)
    }
  }, [])
  return (
    <Box minH="100vh" bg="gray.50" color="gray.900">
      <Box as="header" position="sticky" top={0} zIndex={1100} borderBottomWidth="1px" borderColor="gray.200" bg="linear-gradient(135deg, rgba(48, 128, 52, 1) 0%, rgba(128, 198, 132, 1) 100%)">
        <Flex px={4} py={3} align="center" gap={4}>
          <Flex as={Link} to="/" align="center" gap={2}>
            <Image alt="logo" fit="contain" src="/images/logo.png" />
            <Box as="span" fontSize="lg" fontWeight="semibold" color="gray.50">BioQueue</Box>
          </Flex>
          <Flex as="nav" align="center" gap={2}>
            <Flex align="center" position="relative">
              <Button as={Link} to="/" size="sm" variant="ghost" leftIcon={<i className="fas fa-home"></i>} bg={(loc.pathname === '/jobs') ? 'whiteAlpha.200' : 'transparent'} color="white" _hover={{ bg: 'whiteAlpha.200' }} _active={{ bg: 'whiteAlpha.300' }}>
                Dashboard
              </Button>
              {runningJobsCount > 0 && (
                <Badge
                  position="absolute"
                  top="-2"
                  right="-2"
                  colorScheme="blue"
                  fontSize="xs"
                  minW="18px"
                  h="18px"
                  display="flex"
                  alignItems="center"
                  justifyContent="center"
                  borderRadius="full"
                  zIndex={1}
                >
                  {runningJobsCount > 99 ? '99+' : runningJobsCount}
                </Badge>
              )}
            </Flex>
            <Menu>
              <MenuButton as={Button} size="sm" variant="ghost" leftIcon={<i className="fas fa-database"></i>} bg={(loc.pathname.startsWith('/references') || loc.pathname.startsWith('/virtual-envs')) ? 'whiteAlpha.200' : 'transparent'} color="white" _hover={{ bg: 'whiteAlpha.200' }} _active={{ bg: 'whiteAlpha.300' }} _expanded={{ bg: 'whiteAlpha.300' }}>
                Data
              </MenuButton>
              <MenuList>
                <MenuItem as={Link} to="/references">References</MenuItem>
                <MenuItem as={Link} to="/virtual-envs">Environments</MenuItem>
              </MenuList>
            </Menu>
            {/* job menu removed intentionally to avoid duplication */}
            <Button as={Link} to="/jobs/new" size="sm" variant="ghost" leftIcon={<i className="fas fa-plus"></i>} bg={(loc.pathname === '/jobs/new') ? 'whiteAlpha.200' : 'transparent'} color="white" _hover={{ bg: 'whiteAlpha.200' }} _active={{ bg: 'whiteAlpha.300' }}>
              New Job
            </Button>
            <Menu>
              <MenuButton as={Button} size="sm" variant="ghost" leftIcon={<i className="fas fa-book"></i>} bg={(loc.pathname.startsWith('/protocols')) ? 'whiteAlpha.200' : 'transparent'} color="white" _hover={{ bg: 'whiteAlpha.200' }} _active={{ bg: 'whiteAlpha.300' }} _expanded={{ bg: 'whiteAlpha.300' }}>
                Protocol
              </MenuButton>
              <MenuList>
                <MenuItem as={Link} to="/protocols">Manage Protocols</MenuItem>
                <MenuItem as={Link} to="/protocols/new">New Protocol</MenuItem>
              </MenuList>
            </Menu>
          </Flex>
          <Spacer />
          <Flex align="center" gap={3} fontSize="sm">
            {me?.username ? (
              <Menu>
                <MenuButton as={Button} size="sm" variant="ghost" leftIcon={<i className="fas fa-user"></i>} color="white" _hover={{ bg: 'whiteAlpha.200' }} _active={{ bg: 'whiteAlpha.300' }}>
                  {me.username}
                </MenuButton>
                <MenuList>
                  <MenuItem onClick={handleLogout} isDisabled={loggingOut}>
                    {loggingOut ? 'Logging out...' : 'Logout'}
                  </MenuItem>
                </MenuList>
              </Menu>
            ) : (
              <Button as={Link} to="/login" size="sm" variant="ghost" leftIcon={<i className="fas fa-user"></i>} color="white" _hover={{ bg: 'whiteAlpha.200' }} _active={{ bg: 'whiteAlpha.300' }}>
                Login
              </Button>
            )}
          </Flex>
        </Flex>
      </Box>
      <Box as="main" px={6} py={6}>
        {authChecked ? (
          <Routes>
            <Route path="/" element={<Navigate to="/jobs" replace />} />
            <Route path="/jobs" element={me ? <JobMonitorPage /> : <Navigate to="/login" state={{ from: { pathname: "/jobs" } }} replace />} />
            <Route path="/jobs/new" element={me ? <CreateJobPage /> : <Navigate to="/login" state={{ from: { pathname: "/jobs/new" } }} replace />} />
            <Route path="/protocols" element={me ? <ProtocolsPage /> : <Navigate to="/login" state={{ from: { pathname: "/protocols" } }} replace />} />
            <Route path="/protocols/new" element={me ? <NewProtocolPage /> : <Navigate to="/login" state={{ from: { pathname: "/protocols/new" } }} replace />} />
            <Route path="/references" element={me ? <ReferencesPage /> : <Navigate to="/login" state={{ from: { pathname: "/references" } }} replace />} />
            <Route path="/virtual-envs" element={me ? <VirtualEnvsPage /> : <Navigate to="/login" state={{ from: { pathname: "/virtual-envs" } }} replace />} />
            <Route path="/login" element={me ? <Navigate to="/jobs" replace /> : <LoginPage />} />
          </Routes>
        ) : (
          <Box display="flex" justifyContent="center" alignItems="center" minHeight="50vh">
            <Box textAlign="center">
              <Box className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto mb-4"></Box>
              <Text>Loading...</Text>
            </Box>
          </Box>
        )}
      </Box>
      <Box as="footer" borderTop="1px" borderColor="gray.200" py={4} mt={8}>
        <Box px={4} fontSize="sm" opacity={0.7} textAlign="center">
          <Text>© 2016–{new Date().getFullYear()} Li Yao. BioQueue is licensed under the Apache License 2.0.</Text>
          <Text>Citation: <ChakraLink href="https://yaobio.com">Yao, L.</ChakraLink>, Wang, H., Song, Y. & Sui, G. <ChakraLink href="https://doi.org/10.1093/bioinformatics/btx403">BioQueue: a novel pipeline framework to accelerate bioinformatics analysis</ChakraLink>. <Text as="em">Bioinformatics</Text> 33, 3286–3288 (2017).</Text>
        </Box>
      </Box>
    </Box>
  )
}

declare global {
  interface Window { __app_root?: Root }
}

const container = document.getElementById('root')!
if (!window.__app_root) {
  window.__app_root = createRoot(container)
}
window.__app_root.render(
  <ChakraProvider>
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  </ChakraProvider>
)


