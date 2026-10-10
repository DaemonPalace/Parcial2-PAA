import { gql } from "@apollo/client";

// Each screen asks only for the fields it renders (no over-fetching, FR-12).

export const ME = gql`
  query Me { me { id email role } }
`;

export const CITIES = gql`
  query Cities { cities { code name } }
`;

export const SEARCH = gql`
  query Search($input: PackageSearchInput!) {
    packageAvailability(input: $input) {
      flights(limit: 6) { id airline departAt arriveAt durationMinutes stops priceCop seatsAvailable source }
      hotels(limit: 6) { id name rating priceTotalCop roomsAvailable source }
      cars(limit: 6) { id vendor model category priceTotalCop unitsAvailable source }
      cheapestPackage { totalCop flight { id } hotel { id } car { id } }
    }
  }
`;

export const LOGIN = gql`
  mutation Login($email: String!, $password: String!) {
    login(email: $email, password: $password) { user { id email role } userErrors { code message field } }
  }
`;

export const REGISTER = gql`
  mutation Register($email: String!, $password: String!) {
    register(email: $email, password: $password) { user { id email role } userErrors { code message field } }
  }
`;

export const LOGOUT = gql`
  mutation Logout { logout }
`;

export const BOOK = gql`
  mutation Book($input: BookPackageInput!) {
    bookPackage(input: $input) { order { id status } userErrors { code message } }
  }
`;

export const ORDER = gql`
  query Order($id: ID!) {
    order(id: $id) {
      id status totalCop failureReason createdAt
      flight { airline origin destination departAt priceCop }
      hotel { name city checkIn checkOut priceTotalCop }
      car { vendor model pickupDate dropoffDate priceTotalCop }
      steps { name action status error startedAt endedAt }
    }
  }
`;

export const MY_ORDERS = gql`
  query MyOrders {
    myOrders(first: 30) {
      id status totalCop createdAt
      flight { origin destination departAt }
      hotel { name }
    }
  }
`;

export const TRIGGER_INGESTION = gql`
  mutation TriggerIngestion { triggerIngestion { id state } }
`;

export type UserError = { code: string; message: string; field?: string | null };
export type Me = { id: string; email: string; role: "TRAVELER" | "ADMIN" } | null;

/** Transport-level failures (e.g. HTTP 429 from the rate limiter) as a user-facing message. */
export function requestError(err: unknown): string {
  const status = (err as { statusCode?: number })?.statusCode;
  if (status === 429 || /429/.test(String(err))) return "Demasiadas solicitudes. Espera un minuto e intenta de nuevo.";
  return "No fue posible completar la solicitud.";
}
