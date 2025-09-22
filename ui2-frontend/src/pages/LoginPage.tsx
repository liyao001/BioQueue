import React, { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import {
  Box,
  Button,
  FormControl,
  FormLabel,
  Input,
  Heading,
  VStack,
  Alert,
  AlertIcon,
  AlertTitle,
  AlertDescription,
  Spinner,
  useColorModeValue
} from '@chakra-ui/react'
import { apiPost } from '../lib/api'

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ok, setOk] = useState(false)
  const location = useLocation()

  useEffect(() => { document.title = 'Login – BioQueue' }, [])

  // Form validation
  const isFormValid = username.trim() !== '' && password.trim() !== ''

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!isFormValid) return

    setLoading(true)
    setError(null)
    setOk(false)

    try {
      const res = await apiPost('/auth/login/', JSON.stringify({
        username: username.trim(),
        password: password.trim()
      }))

      if (!res.ok) {
        let errorMessage = 'Login failed'
        try {
          const data = await res.json()
          errorMessage = data.detail || data.message || `HTTP ${res.status}`
        } catch {
          errorMessage = `HTTP ${res.status}: ${res.statusText || 'Unknown error'}`
        }
        throw new Error(errorMessage)
      }

      // Check if login was successful
      const data = await res.json()
      if (data.status === 'ok') {
        setOk(true)
        // Trigger a page reload to refresh authentication state
        setTimeout(() => {
          window.location.href = location.state?.from?.pathname || '/jobs'
        }, 1500)
      } else {
        throw new Error('Unexpected response from server')
      }
    } catch (err: any) {
      console.error('Login error:', err)
      setError(err?.message || 'An unexpected error occurred')
    } finally {
      setLoading(false)
    }
  }

  const bgColor = useColorModeValue('white', 'gray.800')
  const borderColor = useColorModeValue('gray.200', 'gray.600')

  return (
    <Box
      maxW="md"
      mx="auto"
      mt={8}
      p={8}
      bg={bgColor}
      borderWidth={1}
      borderColor={borderColor}
      borderRadius="lg"
      shadow="lg"
    >
      <VStack spacing={6}>
        <Heading size="lg" textAlign="center" color="gray.700">
          Login to BioQueue
        </Heading>

        <Box as="form" onSubmit={submit} w="full">
          <VStack spacing={4}>
            <FormControl isRequired>
              <FormLabel>Username</FormLabel>
              <Input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Enter your username"
                isDisabled={loading}
                autoComplete="username"
                size="lg"
              />
            </FormControl>

            <FormControl isRequired>
              <FormLabel>Password</FormLabel>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your password"
                isDisabled={loading}
                autoComplete="current-password"
                size="lg"
              />
            </FormControl>

            <Button
              type="submit"
              colorScheme="blue"
              size="lg"
              w="full"
              isLoading={loading}
              loadingText="Signing in..."
              isDisabled={!isFormValid}
              spinner={<Spinner size="sm" />}
            >
              Sign In
            </Button>
          </VStack>
        </Box>

        {error && (
          <Alert status="error" borderRadius="md">
            <AlertIcon />
            <Box>
              <AlertTitle>Login Failed!</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Box>
          </Alert>
        )}

        {ok && (
          <Alert status="success" borderRadius="md">
            <AlertIcon />
            <Box>
              <AlertTitle>Login Successful!</AlertTitle>
              <AlertDescription>Redirecting to dashboard...</AlertDescription>
            </Box>
          </Alert>
        )}
      </VStack>
    </Box>
  )
}


