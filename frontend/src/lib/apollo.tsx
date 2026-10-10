"use client";

import { ApolloClient, HttpLink, InMemoryCache } from "@apollo/client";
import { ApolloProvider } from "@apollo/client/react";

// The ONLY backend the browser talks to (FR-10). The session cookie is HttpOnly,
// so it rides along with credentials: "include" and is never visible to JS.
const client = new ApolloClient({
  link: new HttpLink({
    uri: process.env.NEXT_PUBLIC_GRAPHQL_URL ?? "http://localhost:8000/graphql",
    credentials: "include",
  }),
  cache: new InMemoryCache({
    typePolicies: { SagaStep: { keyFields: false }, Package: { keyFields: false } },
  }),
});

export function Providers({ children }: { children: React.ReactNode }) {
  return <ApolloProvider client={client}>{children}</ApolloProvider>;
}
