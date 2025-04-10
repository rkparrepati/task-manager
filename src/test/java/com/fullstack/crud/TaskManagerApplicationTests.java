import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/extend-expect';
import AddApplicationsGrid from '../Components/Applications/wizard/AddApplicationsGrid';
import { BrowserRouter as Router } from 'react-router-dom';
import MockAdapter from 'axios-mock-adapter';
import service from '../Services/apiheader';

const mock = new MockAdapter(service);

describe('AddApplicationsGrid - Happy Path', () => {
  const mockApplicationData = {
    status: 200,
    data: {
      data: {
        applicationdata: {
          productId: '123',
          productType: 'Test Type',
          productName: 'Test Product',
        },
      },
    },
  };

  const mockData = {
    data: {
      content: [
        {
          id: 304,
          identifier: '10000132_Nepal_m5qr8tc7',
          applicationdata: '{"productName":"Metformin Hydrochloride 1000 mg Tablet","producerType":"Jordan Procedure"}',
        },
      ],
    },
    message: 'All applications retrieved successfully',
    status: 200,
  };

  beforeEach(() => {
    mock.onGet('application/v1/display/123').reply(200, mockApplicationData);
    mock.onGet('application/v1/display-all/refresh-products').reply(200, mockData);
  });

  it('renders the AddApplicationsGrid component and displays data correctly', async () => {
    render(
      <Router>
        <AddApplicationsGrid />
      </Router>
    );

    // Wait for the API data to load and render
    await waitFor(() => {
      expect(screen.getByText('Metformin Hydrochloride 1000 mg Tablet')).toBeInTheDocument();
      expect(screen.getByText('Jordan Procedure')).toBeInTheDocument();
    });

    // Verify that the component renders correctly
    expect(screen.getByText('LinkProducts Component')).toBeInTheDocument();
    expect(screen.getByText('LinkCountry Component')).toBeInTheDocument();
    expect(screen.getByText('LinkSection Component')).toBeInTheDocument();
  });
});
